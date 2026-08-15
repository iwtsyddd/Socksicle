"""Process-guard helpers for proxy engine subprocesses.

Two problems are solved here, both rooted in the classic "Only one usage
of each socket address" bind failure reported by xray/sing-box after a
crash left the previous core process alive:

* PID marker files: every engine start records ``{pid, binary}`` into
  ``<config>/engine_state/<engine>.pid``; teardown removes it.  A marker
  left behind after a crash identifies a stale engine process that still
  owns sockets.

* Stale-process cleanup: when a marker exists and the recorded pid is
  alive, the process is killed with ``taskkill /PID <pid> /T /F`` on
  Windows -- a console-less core cannot be stopped gracefully there
  (see sing-box#3806, nekobase/nekoray#111) -- or SIGKILL on POSIX.
  When the live executable path can be resolved and does NOT match the
  recorded binary, the pid was recycled by an unrelated process and
  nothing is killed; the marker is deleted instead.  When the path
  cannot be resolved (permissions, exotic pids) the marker itself is
  treated as the ownership claim and the process is killed anyway, the
  same pragmatic approach nekobox/v2rayN take with zombie cores after
  the main app exited uncleanly.

Port selection follows the scheme used by v2rayN and Clash-family GUIs:
try the canonical port (10085 for the xray gRPC API, 9090 for the
sing-box Clash API) and fall back to the next free port.
"""
import ctypes
import json
import logging
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

from utils.platform_utils import get_config_dir, is_windows

log = logging.getLogger("engine.proc_guard")

STATE_DIR_NAME = "engine_state"
PORT_ATTEMPTS = 50
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
CREATE_NO_WINDOW = 0x08000000
_CMD_TIMEOUT_S = 10.0


def port_available(host: str, port: int) -> bool:
    """Return True when a TCP listener could be bound at host:port now."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, int(port)))
        return True
    except (OSError, ValueError, OverflowError):
        return False


def pick_free_port(preferred: int, host: str = "127.0.0.1",
                   attempts: int = PORT_ATTEMPTS) -> int:
    """Pick a free TCP port, preferring ``preferred`` and scanning upward.

    The preferred try-then-increment scheme keeps the canonical port
    (10085 / 9090) whenever possible and only moves on a conflict; the
    bind/close check is inherently racy, which is acceptable for short
    lived local API listeners.
    """
    try:
        preferred = int(preferred)
    except (TypeError, ValueError):
        preferred = 10085
    for port in range(preferred, min(preferred + attempts, 65535) + 1):
        if port_available(host, port):
            return port
    raise RuntimeError(f"No free TCP port found near {preferred} on {host}")


def _state_dir() -> Path:
    d = get_config_dir() / STATE_DIR_NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.debug("Cannot create engine state dir %s: %s", d, e)
    return d


def marker_path(engine_name: str) -> Path:
    return _state_dir() / f"{engine_name}.pid"


def write_pid_marker(engine_name: str, pid: int, binary: str) -> Path:
    """Atomically record the pid and binary of a started engine process."""
    path = marker_path(engine_name)
    payload = json.dumps({"pid": int(pid), "binary": str(binary),
                          "engine": engine_name})
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        log.warning("Cannot write pid marker %s: %s", path, e)
    return path


def read_pid_marker(engine_name: str) -> dict | None:
    """Read a pid marker, or None when missing or unusable."""
    path = marker_path(engine_name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pid"), int):
        return None
    if data["pid"] <= 0:
        return None
    return data


def remove_pid_marker(engine_name: str) -> None:
    try:
        marker_path(engine_name).unlink(missing_ok=True)
    except OSError as e:
        log.debug("Cannot remove pid marker for %s: %s", engine_name, e)


def process_alive(pid: int) -> bool:
    """Return True when the process with this pid still exists."""
    if is_windows():
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=_CMD_TIMEOUT_S,
                creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return False
        return f'"{pid}"' in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def process_executable_path(pid: int) -> str | None:
    """Best-effort absolute path of the pid's executable, None on failure."""
    if is_windows():
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return None
            try:
                buf = ctypes.create_unicode_buffer(32768)
                size = ctypes.c_ulong(len(buf))
                if not kernel32.QueryFullProcessImageNameW(
                        handle, 0, buf, ctypes.byref(size)):
                    return None
                return buf.value
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            return None
    try:
        exe = os.readlink(f"/proc/{int(pid)}/exe")
    except (OSError, ValueError):
        return None
    if exe.endswith(" (deleted)"):
        exe = exe[:-len(" (deleted)")]
    return exe


def _paths_match(a: str, b: str) -> bool:
    a, b = Path(a), Path(b)
    if a.exists() and b.exists():
        try:
            return a.samefile(b)
        except OSError:
            pass
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def kill_process(pid: int) -> bool:
    """Force-kill the pid; returns True when the process is gone."""
    try:
        if is_windows():
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=_CMD_TIMEOUT_S,
                creationflags=CREATE_NO_WINDOW)
        else:
            os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        return False
    return not process_alive(pid)


def cleanup_stale_engines(engine_names: list[str]) -> list[str]:
    """Kill leftover engine processes from previous sessions.

    Only processes recorded in our own pid markers are ever touched; a
    live pid whose executable does not match the recorded binary is
    treated as recycled and left alone.  Returns a list of human
    readable actions that were performed (empty when nothing to do).
    """
    actions = []
    for name in engine_names:
        try:
            marker = read_pid_marker(name)
        except Exception as e:
            log.warning("Cannot inspect pid marker for %s: %s", name, e)
            continue
        if marker is None:
            continue
        pid = marker["pid"]
        recorded_binary = marker.get("binary")
        if not process_alive(pid):
            remove_pid_marker(name)
            actions.append(f"removed stale pid marker {name} (pid {pid})")
            continue
        live_path = process_executable_path(pid)
        if live_path and recorded_binary and not _paths_match(
                recorded_binary, live_path):
            log.warning(
                "Pid %s recorded for %s now belongs to %s, not %s - "
                "leaving it alone and dropping the marker",
                pid, name, live_path, recorded_binary)
            remove_pid_marker(name)
            actions.append(f"dropped recycled pid marker {name} (pid {pid})")
            continue
        if live_path:
            log.info("Killing stale %s process (pid=%s, exe=%s)",
                     name, pid, live_path)
        else:
            log.warning(
                "Killing stale %s process (pid=%s): could not verify its "
                "executable path, trusting the pid marker",
                name, pid)
        if kill_process(pid):
            remove_pid_marker(name)
            actions.append(f"killed stale {name} process (pid {pid})")
        else:
            log.error("Failed to kill stale %s process (pid=%s)",
                      name, pid)
    return actions