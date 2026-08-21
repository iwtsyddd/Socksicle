"""Abstract base class for proxy engines.

Each engine (sslocal, xray, sing-box) implements this interface so the
connection manager and UI can work with any backend transparently.
"""
import json
import logging
import os
import sys
import subprocess
import tempfile
import threading
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QObject, Signal

from .proc_guard import (
    cleanup_stale_engines,
    port_available,
    wait_for_port_available,
    remove_pid_marker,
    write_pid_marker,
)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

# Default local SOCKS5 proxy listen port; overridden by user settings.
DEFAULT_LOCAL_PORT = 1080

log = logging.getLogger("engine")


class EngineType(str, Enum):
    SSLOCAL = "sslocal"
    XRAY = "xray"
    SINGBOX = "sing-box"


class CheckResult(NamedTuple):
    usable: bool
    reason: str


class InstallResult(NamedTuple):
    ok: bool
    path: Path | None
    reason: str


def set_pdeathsig(sig: int | None = None) -> bool:
    """Set PR_SET_PDEATHSIG on Linux so child process receives SIGTERM when parent dies.

    Uses libc.prctl(PR_SET_PDEATHSIG, sig) via ctypes. Safe to call on any platform
    (no-op on non-Linux).
    """
    if not sys.platform.startswith("linux"):
        return False
    if sig is None:
        import signal
        sig = signal.SIGTERM
    try:
        import ctypes
        import ctypes.util
        PR_SET_PDEATHSIG = 1
        libc_name = ctypes.util.find_library("c") or "libc.so.6"
        try:
            libc = ctypes.CDLL(libc_name, use_errno=True)
        except OSError:
            libc = ctypes.CDLL(None, use_errno=True)
        res = libc.prctl(PR_SET_PDEATHSIG, ctypes.c_ulong(int(sig)), ctypes.c_ulong(0), ctypes.c_ulong(0), ctypes.c_ulong(0))
        return res == 0
    except Exception as e:
        log.debug("Failed to set PR_SET_PDEATHSIG: %s", e)
        return False


class ProxyEngine(QObject):
    """Abstract proxy engine that manages a subprocess providing a local
    SOCKS5/HTTP proxy for a single Shadowsocks (or multi-protocol) server.

    Subclasses must implement: find_binary, check_usable, install,
    build_config, build_args, version_args, process_name.
    """

    statusChanged = Signal(str, bool)
    connectionStateChanged = Signal(bool)
    logUpdated = Signal(str)

    engine_type: EngineType

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self.process = None
        self.local_port = DEFAULT_LOCAL_PORT
        self.is_connected = False
        self.current_server = None
        self.last_exit_code = None
        self._config_path: Path | None = None
        self._marker_name: str | None = None
        self._bind_error_reported = False

    def find_binary(self) -> Path | None:
        """Locate the engine binary on this system."""
        raise NotImplementedError

    def check_usable(self, path) -> CheckResult:
        """Validate whether a binary is usable."""
        raise NotImplementedError

    def install(self, progress_cb=None) -> InstallResult:
        """Download and install the engine binary."""
        raise NotImplementedError

    def build_config(self, server) -> dict:
        """Build the engine-specific configuration dict for a server."""
        raise NotImplementedError

    def build_args(self, server, cmd_prefix: list[str], config_prefix: str = "proxy-") -> list[str]:
        """Build temp config file and return command arguments."""
        config = self.build_config(server)
        fd, path = tempfile.mkstemp(prefix=config_prefix, suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        if sys.platform != "win32":
            os.chmod(path, 0o600)
        self._config_path = Path(path)
        return [*cmd_prefix, path]

    def version_args(self) -> list[str]:
        """Args to get the engine version (e.g. ['--version'])."""
        raise NotImplementedError

    def process_name(self) -> str:
        """Human-readable process name for log messages."""
        raise NotImplementedError

    def exit_message(self, code):
        if sys.platform == "win32" and code is not None:
            c = code & 0xFFFFFFFF
            if c == 0xC0000135:
                return (f"Failed to start {self.process_name()}: Microsoft Visual C++ Redistributable is "
                        "missing. Install vc_redist.x64.exe and try again.")
            if c == 0xC0000139:
                return (f"Failed to start {self.process_name()}: outdated Visual C++ runtime. "
                        "Install the latest vc_redist.x64.exe.")
        return f"Failed to start {self.process_name()} (exit code {code})"

    def start(self, server):
        """Launch the engine subprocess for a server, or report failure.

        Named ``start`` (not ``connect``) because PySide6 shadows a python
        ``connect`` method with ``QObject.connect`` on subclass instances.
        """
        binary = self.find_binary()
        if not binary:
            self.statusChanged.emit(
                f"Error: {self.process_name()} not found. "
                f"Install it and try again.", True)
            return False

        with self._lock:
            if self.is_connected or self.process is not None:
                self.disconnect_from_server()

            # A crashed previous session may have left our engine process
            # alive and holding sockets; kill only what our pid marker owns.
            cleanup_stale_engines([self.engine_type.value])

            if not wait_for_port_available("127.0.0.1", int(self.local_port), timeout=2.0):
                msg = (f"Connection failed: local port {int(self.local_port)} is in "
                       "use by another process. Change the local port in "
                       "Settings or stop the program using it.")
                log.error("%s", msg)
                self.statusChanged.emit(msg, True)
                return False

            try:
                self.current_server = server
                args = [str(binary), *self.build_args(server)]
                bin_dir = str(binary.parent)
                env = os.environ.copy()
                env["ENABLE_DEPRECATED_LEGACY_DNS_SERVERS"] = "true"
                env["ENABLE_DEPRECATED_OUTBOUND_DNS_RULE_ITEM"] = "true"
                env["ENABLE_DEPRECATED_MISSING_DOMAIN_RESOLVER"] = "true"
                env["ENABLE_DEPRECATED_LEGACY_INBOUND_FIELDS"] = "true"
                env["XRAY_LOCATION_ASSET"] = bin_dir
                env["xray.location.asset"] = bin_dir
                env["V2RAY_LOCATION_ASSET"] = bin_dir
                if sys.platform == "win32":
                    env["PATH"] = f"{bin_dir};" + env.get("PATH", "")

                popen_kwargs = {
                    "cwd": bin_dir,
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                    "close_fds": (sys.platform != "win32"),
                    "env": env,
                }
                if sys.platform == "win32":
                    popen_kwargs["creationflags"] = (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
                elif sys.platform.startswith("linux"):
                    popen_kwargs["preexec_fn"] = set_pdeathsig

                self.process = subprocess.Popen(
                    args,
                    **popen_kwargs,
                )
                self._marker_name = self.engine_type.value
                write_pid_marker(self._marker_name, self.process.pid,
                                 str(binary))
                self._bind_error_reported = False
                log.info("Started %s: %s", self.process_name(), binary)
            except (OSError, ValueError, subprocess.SubprocessError) as e:
                log.error("Failed to start %s: %s", self.process_name(), e)
                self.statusChanged.emit(
                    f"Connection failed: {humanize_error(e, self.process_name())}", True)
                self.process = None
                return False

        threading.Thread(target=self._drain, args=(self.process.stdout, False),
                         daemon=True).start()
        threading.Thread(target=self._drain, args=(self.process.stderr, True),
                         daemon=True).start()
        threading.Thread(target=self._monitor, daemon=True).start()
        return True

    def is_running(self):
        with self._lock:
            proc = self.process
            return proc is not None and proc.poll() is None

    def confirm_connected(self):
        with self._lock:
            self.is_connected = True
        self.connectionStateChanged.emit(True)

    def _monitor(self):
        with self._lock:
            proc = self.process
        code = proc.wait() if proc else None
        owned = False
        was_connected = False
        with self._lock:
            if self.process is proc and proc is not None:
                owned = True
                self.process = None
                self.last_exit_code = code
                was_connected = self.is_connected
                self.is_connected = False
        if owned:
            self.connectionStateChanged.emit(False)
            if was_connected:
                log.warning("%s exited unexpectedly (code=%s)",
                            self.process_name(), code)
                self.statusChanged.emit("Connection lost", True)

    def _drain(self, stream, is_err):
        try:
            for line in iter(stream.readline, ""):
                line = line.strip()
                if not line:
                    continue
                low = line.lower()
                is_actual_error = any(w in low for w in ("fatal", "panic", "error"))
                # Only check for startup bind errors before the proxy is confirmed connected
                hint = self._bind_error_hint(line) if (is_err and not self.is_connected) else None
                if hint:
                    log.warning("[%s-log] %s", self.process_name(), hint)
                    self.logUpdated.emit(f"Error: {hint}")
                    if not self._bind_error_reported:
                        self._bind_error_reported = True
                        self.statusChanged.emit(
                            f"Connection failed: {hint}", True)
                elif is_err and is_actual_error:
                    log.warning("[%s-log] %s", self.process_name(), line)
                    self.logUpdated.emit(line)
                else:
                    log.info("[%s-log] %s", self.process_name(), line)
                    self.logUpdated.emit(line)
        except (OSError, ValueError) as e:
            log.debug("[%s] stream read ended: %s", self.process_name(), e)
        finally:
            try:
                stream.close()
            except OSError as e:
                log.debug("[%s] stream close failed: %s", self.process_name(), e)

    def _bind_error_hint(self, line):
        """Translate an engine bind failure line into an actionable hint."""
        if self.is_connected:
            return None
        low = line.lower()
        has_bind_err = any(k in low for k in (
            "address already in use",
            "eaddrinuse",
            "only one usage",
            "failed to bind",
            "failed to listen",
            "cannot bind",
        )) or ("bind" in low and any(k in low for k in ("listen", "listener", "fatal", "failed to start")))
        if not has_bind_err:
            return None

        api_port = getattr(self, "_api_port", None) or \
            getattr(self, "_clash_port", None)
        candidates = [("local SOCKS5 port", int(self.local_port))]
        if api_port:
            candidates.append(("API port", int(api_port)))
        for label, port in candidates:
            if f":{port}" in line:
                hint = (f"Could not bind 127.0.0.1:{port} ({label}) - "
                        f"another {self.process_name()} instance may still "
                        "be running")
                if label == "local SOCKS5 port":
                    hint += (". Stop the conflicting program or change the "
                             "port in Settings.")
                return hint
        if any(k in low for k in ("fatal", "failed to start", "failed to listen", "failed to bind")):
            return (f"Could not bind a local port - is another "
                    f"{self.process_name()} instance still running?")
        return None

    def teardown(self):
        with self._lock:
            proc = self.process
            if proc:
                pid = proc.pid
                log.info("Stopping %s (pid=%s)", self.process_name(), pid)
                if proc.poll() is None:
                    try:
                        if sys.platform == "win32":
                            from .proc_guard import kill_process
                            try:
                                proc.terminate()
                                proc.wait(timeout=0.6)
                            except (OSError, subprocess.TimeoutExpired):
                                try:
                                    proc.kill()
                                    proc.wait(timeout=0.5)
                                except (OSError, subprocess.TimeoutExpired):
                                    pass
                            if proc.poll() is None:
                                kill_process(pid)
                        else:
                            proc.terminate()
                            try:
                                proc.wait(timeout=1.5)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait(timeout=1.0)
                    except (OSError, subprocess.SubprocessError) as e:
                        log.warning("Error stopping %s: %s",
                                    self.process_name(), e)
                self.process = None
            self.is_connected = False
        self._remove_marker()
        self._cleanup_config()

    def _remove_marker(self):
        """Drop the pid marker we wrote when this engine started."""
        if self._marker_name:
            name, self._marker_name = self._marker_name, None
            remove_pid_marker(name)

    def _cleanup_config(self):
        if hasattr(self, '_config_path') and self._config_path and self._config_path.exists():
            try:
                self._config_path.unlink()
            except OSError:
                pass
            self._config_path = None

    def disconnect_from_server(self):
        self.teardown()
        self.connectionStateChanged.emit(False)
        self.statusChanged.emit("Disconnected", False)

    def get_current_server(self):
        with self._lock:
            return self.current_server


def humanize_error(e: BaseException, engine_name: str = "sslocal") -> str:
    from utils.platform_utils import humanize_error as _he
    return _he(e, engine_name)