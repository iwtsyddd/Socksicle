"""sslocal discovery, validation and installation for Socksicle.

Pure standard-library helpers (no Qt, no UI) that locate an existing
shadowsocks-rust ``sslocal`` executable, decide whether it is safe to run,
and, when needed, download the *pinned* official release for this machine,
probe it, and install it atomically.  Network access (``urllib``) is used
only by the provisioning functions :func:`install_sslocal` and
:func:`ensure_sslocal`; a downloaded binary is only ever run after format
probe and ``--version`` validation, and an existing working backend is
never replaced.

Since the download / extract / probe / install steps are identical to the
xray / sing-box pipeline, they are implemented once in
:mod:`utils.engines.common` and reused here; the sslocal-specific pieces
are the release naming, ``tar.xz`` archives, the parallel Range download
and the executable-format validation before anything is executed.

The target triples returned by :func:`detect_target` are the exact names used
by the official shadowsocks-rust release artifacts
(``shadowsocks-<version>.<target>.tar.xz`` / ``.zip``), so a later download
step can build URLs without guessing:

    Windows x64   x86_64-pc-windows-msvc
    Linux x64     x86_64-unknown-linux-musl
    Linux arm64   aarch64-unknown-linux-musl
    macOS x64     x86_64-apple-darwin
    macOS arm64   aarch64-apple-darwin

Linux maps to the static musl builds on purpose: they run identically on
musl and glibc distributions, avoiding "newer glibc required" failures.

Windows ARM64 is rejected explicitly: shadowsocks-rust publishes no
``aarch64-pc-windows-msvc`` artifact.
"""
import logging
import lzma
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
import platform as _platform
from pathlib import Path

from .platform_utils import get_app_dir, get_config_dir, is_windows
from .engines.base import CREATE_NO_WINDOW, CheckResult, InstallResult
from .engines import common
from .engines.common import MIN_PLAUSIBLE_SIZE, VERSION_ARG_TIMEOUT_S, DOWNLOAD_TIMEOUT_S

log = logging.getLogger(__name__)

# Exact release-asset targets for shadowsocks-rust.
WINDOWS_X64 = "x86_64-pc-windows-msvc"
LINUX_X64 = "x86_64-unknown-linux-musl"
LINUX_ARM64 = "aarch64-unknown-linux-musl"
MACOS_X64 = "x86_64-apple-darwin"
MACOS_ARM64 = "aarch64-apple-darwin"

# Pinned official shadowsocks-rust release. Never "latest": the URL is
# derived only from this constant plus the machine's target mapping.
SSLOCAL_VERSION = "v1.24.0"
RELEASE_BASE_URL = "https://github.com/shadowsocks/shadowsocks-rust/releases/download"
VERSION_MARKER_NAME = ".sslocal-version"
_USER_AGENT = "Socksicle (sslocal provisioning)"

_PARALLEL_WORKERS = common.DEFAULT_PARALLEL_WORKERS
# Temp files of parallel downloads live next to the destination so the
# final concatenation stays on one filesystem.
_PARALLEL_TEMP_PREFIX = ".sslocal-part"

_PE_MAGIC = b"MZ"
_ELF_MAGIC = b"\x7fELF"
_MACHO_MAGICS = frozenset({
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",  # 32-bit, BE/LE
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",  # 64-bit, BE/LE
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # fat binary, BE/LE
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",  # fat 64-bit, BE/LE
})

_X64_ALIASES = frozenset({"amd64", "x86_64"})
_ARM64_ALIASES = frozenset({"arm64", "aarch64"})


def _machine_class(machine: str) -> str | None:
    """Normalize a platform.machine() value to 'x86_64', 'arm64' or None."""
    normalized = (machine or "").strip().lower()
    if normalized in _X64_ALIASES:
        return "x86_64"
    if normalized in _ARM64_ALIASES:
        return "arm64"
    return None


def _detect_target(sys_platform: str, machine: str) -> str:
    """Pure mapping of (sys.platform, platform.machine()) -> target triple.

    Raises ValueError for anything that has no official, compatible
    shadowsocks-rust release artifact.
    """
    arch = _machine_class(machine)
    if sys_platform == "win32":
        if arch == "x86_64":
            return WINDOWS_X64
        if arch == "arm64":
            raise ValueError(
                "Windows ARM64 is not supported: shadowsocks-rust publishes "
                "no aarch64-pc-windows-msvc release artifact.")
        raise ValueError(
            f"Unsupported CPU architecture on Windows: {machine!r}. "
            f"Only x86_64 is supported.")
    if sys_platform.startswith("linux"):
        if arch == "x86_64":
            return LINUX_X64
        if arch == "arm64":
            return LINUX_ARM64
        raise ValueError(
            f"Unsupported CPU architecture on Linux: {machine!r}. "
            f"Only x86_64 and arm64 are supported.")
    if sys_platform == "darwin":
        if arch == "x86_64":
            return MACOS_X64
        if arch == "arm64":
            return MACOS_ARM64
        raise ValueError(
            f"Unsupported CPU architecture on macOS: {machine!r}. "
            f"Only x86_64 and arm64 are supported.")
    raise ValueError(
        f"Unsupported platform: {sys_platform!r}. "
        f"Socksicle supports Windows, Linux and macOS.")


def detect_target() -> str:
    """Detect the current OS and CPU architecture and return the exact
    shadowsocks-rust release target for this machine."""
    return _detect_target(sys.platform, _platform.machine())


def _expected_format() -> str:
    """Executable format the *current* machine can run: pe/elf/macho."""
    if is_windows():
        return "pe"
    if sys.platform == "darwin":
        return "macho"
    return "elf"


_FORMAT_NAMES = {"pe": "Windows PE", "elf": "ELF", "macho": "Mach-O"}


def _format_for_magic(magic: bytes) -> str | None:
    if magic.startswith(_PE_MAGIC):
        return "pe"
    if magic.startswith(_ELF_MAGIC):
        return "elf"
    if magic[:4] in _MACHO_MAGICS:
        return "macho"
    return None


def file_format(path: Path) -> str | None:
    """Detect the executable format of a file: 'pe', 'elf', 'macho' or None."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return None
    return _format_for_magic(magic)


def _is_plausible_candidate(path: Path) -> bool:
    """Cheap static check: exists, big enough, right format, executable bit.

    Does not run the binary; use :func:`is_usable` for runtime verification.
    """
    if not path.is_file():
        return False
    try:
        if path.stat().st_size <= MIN_PLAUSIBLE_SIZE:
            return False
    except OSError:
        return False
    if not is_windows() and not os.access(path, os.X_OK):
        return False
    if file_format(path) != _expected_format():
        return False
    return True


def find_sslocal() -> Path | None:
    """Locate sslocal across app-owned, user-config and PATH locations.

    Search order:
      1. app-owned bin directory (bundled / frozen build)
      2. user config bin directory (application-managed)
      3. bin/<engine>/ subdirectories next to the app and in user config
      4. system PATH

    Only returns paths that look like a real executable for this platform;
    a stub or foreign binary is skipped, never returned.
    """
    name = "sslocal.exe" if is_windows() else "sslocal"
    for candidate in (get_app_dir() / "bin" / name,
                      get_config_dir() / "bin" / name,
                      get_app_dir() / "bin" / "sslocal" / name,
                      get_config_dir() / "bin" / "sslocal" / name):
        if _is_plausible_candidate(candidate):
            return candidate
    found = shutil.which(name)
    if found and _is_plausible_candidate(Path(found)):
        return Path(found)
    return None


def is_usable(path) -> CheckResult:
    """Verify an existing local sslocal file before it is executed.

    Checks existence, plausibility, executable format and finally runs
    ``sslocal --version``; ``usable`` is True only if the command exits
    successfully.  Never downloads or fetches anything.
    """
    if path is None:
        return CheckResult(False, "No sslocal path given.")
    if not isinstance(path, (str, os.PathLike)):
        return CheckResult(False, f"Not a valid path: {path!r}")
    p = Path(path)
    if not p.is_file():
        return CheckResult(False, f"Not a file: {p}")
    try:
        size = p.stat().st_size
    except OSError as e:
        return CheckResult(False, f"Cannot stat {p}: {e}")
    if size <= MIN_PLAUSIBLE_SIZE:
        return CheckResult(False, f"Rejected {p}: smaller than "
                                  f"{MIN_PLAUSIBLE_SIZE} bytes; likely a stub.")
    detected = file_format(p)
    expected = _expected_format()
    if detected != expected:
        return CheckResult(
            False,
            f"Rejected {p}: {_FORMAT_NAMES.get(detected, detected or 'no recognizable')} "
            f"file, but this machine runs {_FORMAT_NAMES[expected]} executables.")
    if not is_windows() and not os.access(p, os.X_OK):
        return CheckResult(False, f"Not executable: {p}")
    try:
        flags = CREATE_NO_WINDOW if is_windows() else 0
        proc = subprocess.run(
            [str(p), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=VERSION_ARG_TIMEOUT_S,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return CheckResult(False, f"Could not run {p.name} --version: {e}")
    if proc.returncode != 0:
        return CheckResult(
            False, f"{p.name} --version exited with code {proc.returncode}.")
    return CheckResult(True, "")


# ---------------------------------------------------------------------------
# Provisioning: download, probe, install (stdlib only, shared pipeline).
# ---------------------------------------------------------------------------

def artifact_filename(version: str, target: str) -> str:
    """Official release archive name for a pinned version and target.

    Built strictly from the verified version and the known target mapping;
    never from arbitrary remote or user input.
    """
    suffix = "zip" if "windows" in target else "tar.xz"
    return f"shadowsocks-{version}.{target}.{suffix}"


_VERSION_RE = re.compile(r"v?\d+\.\d+(\.\d+)?")


def _normalize_version(version: str) -> str:
    """Validate a pinned version and normalize it to canonical 'vX.Y.Z'."""
    v = (version or "").strip()
    if not _VERSION_RE.fullmatch(v):
        raise ValueError(
            f"Invalid backend version: {version!r}. "
            "Must look like '1.24.0' or 'v1.24.0'.")
    return "v" + v.lstrip("v")


def _temp_path(dest_dir: Path, suffix: str) -> Path:
    """Fresh temp file *inside* dest_dir so os.replace stays on one fs."""
    return common._temp_path(dest_dir, ".sslocal-", suffix)


def _open_url(url: str, extra_headers=None):
    """Open url with the sslocal User-Agent plus optional extra headers."""
    return common._open_url(url, extra_headers=extra_headers,
                            user_agent=_USER_AGENT)


def _probe_range_support(url: str) -> int | None:
    """Probe whether the server supports HTTP Range requests; returns the
    total file size on a 206 with Content-Range, None otherwise."""
    return common._probe_range_support(url, open_url=_open_url)


def _download_range_worker(url: str, start: int, end: int, part_path: Path,
                           progress_lock: threading.Lock,
                           progress_state: dict,
                           progress_cb=None) -> None:
    """Download a single byte range into part_path, reporting aggregate
    progress through the shared progress_state dict."""
    return common._download_range_worker(
        url, start, end, part_path, progress_lock, progress_state,
        progress_cb=progress_cb, open_url=_open_url)


def _download_archive_parallel(url: str, dest: Path, total_size: int,
                               progress_cb=None) -> None:
    """Download url into dest using parallel byte-range workers; any worker
    failure propagates and the caller falls back to a single stream."""
    return common._download_parallel(
        url, dest, total_size, progress_cb=progress_cb,
        workers=_PARALLEL_WORKERS, temp_prefix=_PARALLEL_TEMP_PREFIX,
        worker_fn=_download_range_worker)


def _download_archive(url: str, dest: Path, progress_cb=None) -> None:
    """Stream url into dest, attempting the parallel download first.

    Tries the parallel download when the server supports Range requests and
    provides a usable total size.  Falls back to a single stream when Range
    is not supported, the size is unknown, or any parallel download fails.
    ``progress_cb``, when given, is called as
    ``progress_cb(downloaded_bytes, total_bytes_or_None)``.
    """
    return common._download(
        url, dest, progress_cb=progress_cb, parallel=True,
        open_url=_open_url, probe=_probe_range_support,
        parallel_fn=_download_archive_parallel,
        temp_prefix=_PARALLEL_TEMP_PREFIX)


def _extract_sslocal(archive: Path, dest: Path, use_exe_name: bool,
                     zip_archive: bool) -> bool:
    """Copy the sslocal member of a verified archive to dest.

    Only the single sslocal file is handled; nothing is extracted wholesale.
    Returns False when the archive contains no sslocal member.  Raises on
    structurally corrupt archives (caller maps to a structured failure).
    """
    wanted = "sslocal.exe" if use_exe_name else "sslocal"
    fmt = "zip" if zip_archive else "tar.xz"
    return common._extract_archive(archive, dest, wanted, fmt)


def install_sslocal(version: str = SSLOCAL_VERSION,
                    progress_cb=None) -> InstallResult:
    """Download, probe and atomically install the pinned sslocal backend.

    Never upgrades an existing backend silently: pass through
    :func:`ensure_sslocal` to reuse one.  An existing managed binary is only
    replaced by ``os.replace`` after the new file passed format and
    ``--version`` validation; every failure path returns a structured
    :class:`InstallResult` and leaves previous state untouched.

    ``progress_cb``, when given, is forwarded to the archive download as
    ``progress_cb(downloaded_bytes, total_bytes_or_None)``.
    """
    try:
        target = detect_target()
    except ValueError as e:
        return InstallResult(False, None, f"Unsupported platform: {e}")
    try:
        version = _normalize_version(version)
    except ValueError as e:
        return InstallResult(False, None, str(e))

    name = "sslocal.exe" if is_windows() else "sslocal"
    dest_dir = get_config_dir() / "bin"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return InstallResult(False, None, f"Cannot create backend directory: {e}")
    managed = dest_dir / name

    archive_name = artifact_filename(version, target)
    archive_url = f"{RELEASE_BASE_URL}/{version}/{archive_name}"

    archive_tmp = install_tmp = None
    try:
        archive_tmp = _temp_path(dest_dir, ".part")
        try:
            _download_archive(archive_url, archive_tmp,
                              progress_cb=progress_cb)
        except urllib.error.HTTPError as e:
            return InstallResult(
                False, None, f"Download failed (HTTP {e.code}): {archive_name}")
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", None) or e
            return InstallResult(False, None, f"Download failed: {reason}")
        except (TimeoutError, socket.timeout):
            return InstallResult(False, None, "Download failed: timed out")

        install_tmp = _temp_path(dest_dir, f".{name}.tmp")
        try:
            found = _extract_sslocal(
                archive_tmp, install_tmp,
                use_exe_name=is_windows(), zip_archive=("windows" in target))
        except (tarfile.TarError, lzma.LZMAError, zipfile.BadZipFile,
                EOFError, OSError) as e:
            return InstallResult(False, None, f"Downloaded archive is corrupt: {e}")
        if not found:
            return InstallResult(
                False, None, "sslocal binary not found inside the archive.")

        try:
            if not is_windows():
                os.chmod(install_tmp, 0o755)
            check = is_usable(install_tmp)
            if not check.usable:
                return InstallResult(
                    False, None,
                    f"Downloaded binary failed validation: {check.reason}")
            # All checks passed: swap into place atomically.
            os.replace(install_tmp, managed)
            common._write_marker(dest_dir, VERSION_MARKER_NAME, version,
                                 ".sslocal-")
        except OSError as e:
            return InstallResult(False, None, f"Installation failed: {e}")
        return InstallResult(True, managed, "")
    finally:
        for tmp in (archive_tmp, install_tmp):
            if tmp is None:
                continue
            try:
                tmp.unlink(missing_ok=True)
            except OSError as e:
                log.debug("Failed to remove temp file %s: %s", tmp, e)


def ensure_sslocal(version: str = SSLOCAL_VERSION,
                   progress_cb=None) -> InstallResult:
    """Return a usable sslocal, downloading it only when required.

    If a plausible sslocal already exists and passes :func:`is_usable`, it is
    reused as-is (no auto-upgrade).  Otherwise the pinned version is
    downloaded, verified and installed via :func:`install_sslocal`, which
    receives ``progress_cb`` (see there for its signature).
    """
    existing = find_sslocal()
    if existing is not None:
        check = is_usable(existing)
        if check.usable:
            return InstallResult(True, existing, "Reusing existing sslocal.")
    return install_sslocal(version, progress_cb=progress_cb)


def installed_version() -> str | None:
    """Version marker of the managed backend, or None when absent."""
    marker = get_config_dir() / "bin" / VERSION_MARKER_NAME
    try:
        content = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return content or None