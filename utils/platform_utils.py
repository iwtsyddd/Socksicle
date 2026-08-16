"""Cross-platform helpers for Socksicle.

Centralizes config paths, binary discovery, logging, and Windows-specific
utilities so the UI layer stays clean and Windows-safe.
"""
import os
import sys
import subprocess
import logging
import platform
from pathlib import Path
from logging.handlers import RotatingFileHandler

log = logging.getLogger(__name__)


def get_app_dir() -> Path:
    """Application directory (where sslocal.exe is bundled when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_windows() -> bool:
    return sys.platform == "win32"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def get_config_dir() -> Path:
    """OS-correct user config directory that needs no admin rights."""
    if is_windows():
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    d = base / "socksicle"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_log_dir() -> Path:
    """OS-correct writable log directory."""
    if is_windows():
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = get_config_dir()
    d = base / "socksicle" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_sslocal() -> Path | None:
    """Locate sslocal. Single source of truth: utils.ss_backend.find_sslocal."""
    from .ss_backend import find_sslocal as _find_sslocal
    return _find_sslocal()


def is_admin() -> bool:
    """Best-effort Windows admin check. Returns False off-Windows."""
    if not is_windows():
        return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError) as e:
        log.debug("Admin check failed: %s", e)
        return False


def elevate_restart() -> bool:
    """Restart the current application with Administrator privileges on Windows."""
    if not is_windows():
        return False
    try:
        import ctypes
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{sys.argv[0]}" {params}'.strip(), None, 1
        )
        if int(ret) > 32:
            sys.exit(0)
        return False
    except Exception as e:
        log.warning("Elevation restart failed: %s", e)
        return False


def windows_dark_mode() -> bool | None:
    """Return True (dark), False (light), or None when unknown."""
    if not is_windows():
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return val == 0
    except OSError:
        return None


def setup_logging(level: int = logging.INFO) -> Path:
    """Rotating file + stderr logging. Returns the active log path."""
    log_path = get_log_dir() / "socksicle.log"
    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handlers = [handler]
    if sys.stderr:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger().info(f"Socksicle starting (pid={os.getpid()}, platform={platform.platform()})")
    return log_path


# MSVC / loader error codes commonly seen when sslocal.exe fails on Windows.
_WIN_ERROR_CODES = {
    0xC0000135: "Microsoft Visual C++ Redistributable (vcruntime140/msvcp140) is missing. "
                "Install it from: https://aka.ms/vs/17/release/vc_redist.x64.exe",
    0xC0000139: "Visual C++ runtime is outdated. Install the latest vc_redist.x64.exe.",
    5:          "Access denied. Check file/folder permissions.",
    0x80070005: "Access denied (Win32 API). Check folder permissions.",
    0x80070002: "A required file was not found.",
}


def humanize_error(e: BaseException, engine_name: str = "sslocal") -> str:
    """Map common Windows exceptions to friendly user messages."""
    if isinstance(e, FileNotFoundError):
        return f"Required component missing ({engine_name}.exe). Run the installer again."
    if isinstance(e, PermissionError):
        return "Access denied. Try a standard (non-admin) run or check file permissions."
    if isinstance(e, subprocess.SubprocessError):
        return f"The proxy process failed: {e}"

    winerror = getattr(e, "winerror", None)
    if winerror is None and isinstance(e, OSError):
        winerror = e.errno
    if winerror and (winerror in _WIN_ERROR_CODES or winerror & 0xFFFFFFFF in _WIN_ERROR_CODES):
        key = winerror if winerror in _WIN_ERROR_CODES else winerror & 0xFFFFFFFF
        return _WIN_ERROR_CODES[key]

    lines = e.errno_text if hasattr(e, "errno_text") else None
    return str(e)