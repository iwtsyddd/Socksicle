"""Shared provisioning pipeline for proxy engine binaries.

xray, sing-box and sslocal follow the same install pipeline: detect a
release target for this machine, locate an existing binary, validate it,
and when needed download a pinned release, extract the single binary,
probe it with ``--version`` and install it atomically (``os.replace``)
together with an installed-version marker.  Everything that differs
between engines lives in a small :class:`InstallProfile`: archive format
(zip / tar.xz / raw), binary name, size threshold, optional parallel
Range-based download, install location and platform specifics (``chmod``
only off Windows, ``CREATE_NO_WINDOW`` on Windows).  Shared byte-copy and
download helpers live here once instead of being duplicated per engine.
"""
import lzma
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, NamedTuple

from .base import CheckResult, InstallResult, CREATE_NO_WINDOW

log = logging.getLogger("engine.common")

MIN_PLAUSIBLE_SIZE = 1_000_000
VERSION_ARG_TIMEOUT_S = 10.0
DOWNLOAD_TIMEOUT_S = 30.0
CHUNK_SIZE = 64 * 1024          # streaming copy buffer for downloads/extracts
DEFAULT_PARALLEL_WORKERS = 4
_USER_AGENT = "Socksicle (engine provisioning)"

# (platform class, architecture) -> release asset target
TargetMap = dict[tuple[str, str], str]


class InstallProfile(NamedTuple):
    """Engine-specific release naming for the shared install pipeline."""
    engine_name: str
    version: str
    release_base_url: str
    marker_name: str
    temp_prefix: str
    target_map: TargetMap
    archive_name: Callable[[str, str], str]
    archive_format: str = "zip"       # 'zip' | 'tar.xz' | 'raw'
    min_size: int = MIN_PLAUSIBLE_SIZE
    parallel: bool = False            # try Range-request parallel download
    binary_name: str | None = None    # defaults to engine_name
    version_args: tuple = ("version",)


def _detect_target(target_map: TargetMap) -> str:
    """Map (sys.platform, platform.machine()) to a release target string."""
    arch = platform.machine().lower()
    sys_plat = sys.platform
    if sys_plat == "win32":
        key = ("windows", arch)
    elif sys_plat.startswith("linux"):
        key = ("linux", arch)
    elif sys_plat == "darwin":
        key = ("darwin", arch)
    else:
        raise ValueError(f"Unsupported platform: {sys_plat}")
    try:
        return target_map[key]
    except KeyError:
        raise ValueError(
            f"Unsupported platform/arch: {key[0]}/{arch}") from None


def _binary_name(engine_name: str) -> str:
    return f"{engine_name}.exe" if sys.platform == "win32" else engine_name


def _local_bin_subdir(engine_name: str) -> str:
    """Subdirectory under bin/ where a manually-placed binary is expected."""
    return engine_name.replace("-", "")


def _find_binary(engine_name: str,
                 min_size: int = MIN_PLAUSIBLE_SIZE) -> Path | None:
    """Locate an engine binary across app, config and PATH locations."""
    from utils.platform_utils import get_config_dir, get_app_dir
    name = _binary_name(engine_name)
    subdir = _local_bin_subdir(engine_name)
    for candidate in (get_app_dir() / "bin" / name,
                      get_config_dir() / "bin" / name,
                      get_app_dir() / "bin" / subdir / name,
                      get_config_dir() / "bin" / subdir / name):
        if candidate.is_file() and candidate.stat().st_size > min_size:
            return candidate
    found = shutil.which(name)
    if found:
        p = Path(found)
        if p.is_file() and p.stat().st_size > min_size:
            return p
    return None


def _check_usable(path, display_name, version_arg=("version",),
                  min_size: int = MIN_PLAUSIBLE_SIZE) -> CheckResult:
    """Validate that a binary exists, looks real, and answers --version."""
    if path is None:
        return CheckResult(False, f"No {display_name} path given.")
    p = Path(path)
    if not p.is_file():
        return CheckResult(False, f"Not a file: {p}")
    try:
        if p.stat().st_size <= min_size:
            return CheckResult(False, f"Rejected {p}: too small")
    except OSError as e:
        return CheckResult(False, f"Cannot stat {p}: {e}")
    try:
        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.run(
            [str(p), *version_arg],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=VERSION_ARG_TIMEOUT_S,
            creationflags=flags,
        )
        if proc.returncode == 0:
            return CheckResult(True, "")
        return CheckResult(
            False,
            f"{display_name} version exited with code {proc.returncode}")
    except (OSError, subprocess.SubprocessError) as e:
        return CheckResult(False, f"Could not run {p.name}: {e}")


def copy_stream(src, out, chunk_size: int = CHUNK_SIZE) -> int:
    """Copy src to out in bounded chunks; returns the number of bytes."""
    copied = 0
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            break
        out.write(chunk)
        copied += len(chunk)
    return copied


def _open_url(url: str, extra_headers=None,
              user_agent: str = _USER_AGENT):
    """Open url with a stable User-Agent plus optional extra headers."""
    headers = {"User-Agent": user_agent}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S)


def _probe_range_support(url: str, open_url=None) -> int | None:
    """Probe whether the server supports HTTP Range requests.

    Sends ``Range: bytes=0-0`` and returns the total file size from the
    ``Content-Range`` header when the server responds with ``206 Partial
    Content``.  Returns ``None`` when Range requests are not supported or
    the total size cannot be determined.
    """
    open_url = open_url or _open_url
    try:
        with open_url(url, {"Range": "bytes=0-0"}) as resp:
            if getattr(resp, "status", None) == 206:
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    try:
                        return int(content_range.rsplit("/", 1)[1])
                    except (ValueError, IndexError):
                        log.debug("Unparseable Content-Range: %s",
                                  content_range)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError,
            TimeoutError, socket.timeout) as e:
        log.debug("Range probe failed for %s: %s", url, e)
    return None


def _download_range_worker(url: str, start: int, end: int, part_path: Path,
                           progress_lock: threading.Lock,
                           progress_state: dict,
                           progress_cb=None, open_url=None) -> None:
    """Download a single byte range into part_path, reporting aggregate
    progress through the shared progress_state dict."""
    open_url = open_url or _open_url
    range_header = f"bytes={start}-{end}"
    downloaded = 0
    with open_url(url, {"Range": range_header}) as resp, \
            open(part_path, "wb") as out:
        while True:
            chunk = resp.read(CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if progress_cb is not None:
                with progress_lock:
                    progress_state["downloaded"] += downloaded
                    progress_cb(progress_state["downloaded"],
                                progress_state["total"])
                    downloaded = 0


def _download_parallel(url: str, dest: Path, total_size: int,
                       progress_cb=None,
                       workers: int = DEFAULT_PARALLEL_WORKERS,
                       temp_prefix: str = ".part",
                       worker_fn=None) -> None:
    """Download url into dest with N parallel byte-range workers.

    Each worker downloads its own chunk to a separate temp file.  After all
    workers complete, the parts are concatenated in order into dest.  Any
    worker failure propagates; the caller falls back to a single stream.
    """
    worker_fn = worker_fn or _download_range_worker
    chunk_size = total_size // workers
    ranges = []
    for i in range(workers):
        start = i * chunk_size
        end = (start + chunk_size - 1) if i < workers - 1 \
            else (total_size - 1)
        ranges.append((start, end))

    part_dir = dest.parent
    part_paths = []
    progress_lock = threading.Lock()
    progress_state = {"downloaded": 0, "total": total_size}

    for i in range(workers):
        fd, name = tempfile.mkstemp(prefix=temp_prefix, suffix=".tmp",
                                    dir=part_dir)
        os.close(fd)
        part_paths.append(Path(name))

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for i, (start, end) in enumerate(ranges):
                futures.append(pool.submit(
                    worker_fn, url, start, end, part_paths[i],
                    progress_lock, progress_state, progress_cb))
            for f in as_completed(futures):
                f.result()

        with open(dest, "wb") as out:
            for part_path in part_paths:
                with open(part_path, "rb") as inp:
                    copy_stream(inp, out)
    finally:
        for p in part_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError as e:
                log.debug("Failed to remove temp part %s: %s", p, e)


def _download_single(url: str, dest: Path, progress_cb=None,
                     open_url=None) -> None:
    """Stream url into dest in one pass, reporting progress when given.

    ``progress_cb`` receives ``progress_cb(downloaded_bytes, total)`` after
    every read chunk; ``total`` comes from the ``Content-Length`` header and
    is ``None`` when the server does not provide one.
    """
    open_url = open_url or _open_url
    total = None
    with open_url(url) as resp, open(dest, "wb") as out:
        if progress_cb is not None:
            header = getattr(resp, "headers", None)
            if header is not None:
                try:
                    total = int(header.get("Content-Length"))
                    if total < 0:
                        total = None
                except (AttributeError, TypeError, ValueError):
                    total = None
        downloaded = 0
        while True:
            chunk = resp.read(CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)
            if progress_cb is not None:
                downloaded += len(chunk)
                progress_cb(downloaded, total)


def _download(url: str, dest: Path, progress_cb=None, parallel: bool = False,
              open_url=None, probe=None, parallel_fn=None,
              workers: int = DEFAULT_PARALLEL_WORKERS,
              temp_prefix: str = ".part") -> None:
    """Download url into dest; with parallel=True, try byte-range workers
    first (only when the server supports Range) and fall back to a single
    stream on any failure.  ``probe`` / ``parallel_fn`` let callers that
    keep their own download helpers stay in control of those steps."""
    open_url = open_url or _open_url
    if parallel:
        total_size = probe(url) if probe is not None \
            else _probe_range_support(url, open_url=open_url)
        if total_size is not None and total_size > 0:
            try:
                if parallel_fn is not None:
                    parallel_fn(url, dest, total_size, progress_cb=progress_cb)
                else:
                    _download_parallel(url, dest, total_size,
                                       progress_cb=progress_cb,
                                       workers=workers,
                                       temp_prefix=temp_prefix)
                return
            except (urllib.error.HTTPError, urllib.error.URLError, OSError,
                    TimeoutError, socket.timeout, ValueError) as e:
                log.debug("Parallel download failed, falling back to "
                          "single stream: %s", e)
    _download_single(url, dest, progress_cb=progress_cb, open_url=open_url)


def _basename(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _extract_archive(archive: Path, dest: Path, name: str,
                     archive_format: str = "zip") -> bool:
    """Copy the single wanted member of an archive to dest.

    ``archive_format`` is one of 'zip', 'tar.xz' or 'raw' (the downloaded
    file itself is the binary, no archive).  Names are matched
    case-insensitively on the last path component.  Returns False when the
    archive contains no matching member; raises on structurally corrupt
    archives (the caller maps to a structured failure).
    """
    if archive_format == "raw":
        with open(archive, "rb") as src, open(dest, "wb") as out:
            copy_stream(src, out)
        return True
    if archive_format == "tar.xz":
        with tarfile.open(archive, mode="r:xz") as tf:
            for member in tf:
                if not member.isfile():
                    continue
                if _basename(member.name) == name:
                    src = tf.extractfile(member)
                    if src is None:
                        return False
                    with src, open(dest, "wb") as out:
                        copy_stream(src, out)
                    return True
        return False
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            if _basename(member) == name:
                with zf.open(member) as src, open(dest, "wb") as out:
                    copy_stream(src, out)
                return True
    return False


def _temp_path(dest_dir: Path, prefix: str, suffix: str) -> Path:
    """Fresh temp file *inside* dest_dir so os.replace stays on one fs."""
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=dest_dir)
    os.close(fd)
    return Path(name)


def _write_marker(dest_dir: Path, marker_name: str, version: str,
                  temp_prefix: str) -> None:
    """Atomically write the installed-version marker into dest_dir."""
    marker_tmp = _temp_path(dest_dir, temp_prefix, ".version.tmp")
    try:
        marker_tmp.write_text(f"{version}\n", encoding="utf-8")
        os.replace(marker_tmp, dest_dir / marker_name)
    finally:
        try:
            marker_tmp.unlink(missing_ok=True)
        except OSError as e:
            log.debug("Failed to remove marker temp %s: %s", marker_tmp, e)


def _install(profile: InstallProfile, progress_cb=None) -> InstallResult:
    """Download, probe and atomically install a pinned engine release.

    Pipeline: detect target -> download (optionally parallel) -> extract ->
    ``chmod`` (POSIX only) -> ``--version`` probe -> ``os.replace`` plus
    version marker.  Every failure path returns a structured
    :class:`InstallResult` and leaves any previous state untouched.
    """
    from utils.platform_utils import get_config_dir
    try:
        target = _detect_target(profile.target_map)
    except ValueError as e:
        return InstallResult(False, None, str(e))

    name = _binary_name(profile.binary_name or profile.engine_name)
    dest_dir = get_config_dir() / "bin"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return InstallResult(False, None, f"Cannot create directory: {e}")

    archive_name = profile.archive_name(profile.version, target)
    archive_url = f"{profile.release_base_url}/{profile.version}/{archive_name}"
    managed = dest_dir / name

    archive_suffix = ".raw" if profile.archive_format == "raw" else ".part"
    archive_tmp = _temp_path(dest_dir, profile.temp_prefix, archive_suffix)
    install_tmp = _temp_path(dest_dir, f".{name}-", ".tmp")

    try:
        _download(archive_url, archive_tmp, progress_cb=progress_cb,
                  parallel=profile.parallel,
                  temp_prefix=f"{profile.temp_prefix}part")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError,
            TimeoutError) as e:
        return InstallResult(False, None, f"Download failed: {e}")

    try:
        if not _extract_archive(archive_tmp, install_tmp,
                                name.lower(), profile.archive_format):
            return InstallResult(False, None, f"{name} not found in archive")
    except (zipfile.BadZipFile, tarfile.TarError, lzma.LZMAError,
            EOFError) as e:
        return InstallResult(False, None, f"Corrupt archive: {e}")

    try:
        if sys.platform != "win32":
            os.chmod(install_tmp, 0o755)
        check = _check_usable(install_tmp, profile.engine_name,
                              version_arg=profile.version_args,
                              min_size=profile.min_size)
        if not check.usable:
            return InstallResult(False, None,
                                 f"Validation failed: {check.reason}")
        os.replace(install_tmp, managed)
        _write_marker(dest_dir, profile.marker_name, profile.version,
                      profile.temp_prefix)
    except OSError as e:
        return InstallResult(False, None, f"Installation failed: {e}")
    finally:
        for tmp in (archive_tmp, install_tmp):
            try:
                tmp.unlink(missing_ok=True)
            except OSError as e:
                log.debug("Failed to remove temp file %s: %s", tmp, e)

    return InstallResult(True, managed, "")