"""Windows-specific startup behavior, isolated behind small functions.

The shared entry point (:mod:`main`) runs the same flow on every platform
and delegates the Windows-only pieces here:

    application start
      -> platform initialization (env, logging, user model id, excepthook)
      -> backend provisioning
      -> create main window
      -> install tray/power handlers if supported
      -> start Qt event loop

On non-Windows platforms every helper degrades to a safe no-op, so Linux
startup and logging behavior stays unchanged.  Windows keeps its high-DPI
environment, file logging, AppUserModelID, unhandled-exception hook, tray
persistence across Explorer restarts (WM_TASKBARCREATED) and reconnect
after sleep/hibernate resume (WM_POWERBROADCAST).
"""
import os
import sys

# Must be applied before Qt/PySide6 is imported on Windows; plain
# assignment so the env vars take effect before Qt initialises.
if sys.platform == "win32":
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

import logging
import traceback
from PySide6.QtCore import QAbstractNativeEventFilter, Qt

from utils.platform_utils import is_windows, setup_logging

log = logging.getLogger(__name__)

# Native event messages (WinUser.h)
WM_TASKBARCREATED = 0x0219      # Explorer restarted -> re-register tray icon
WM_POWERBROADCAST = 0x0218
PBT_APMRESUMESUSPEND = 0x0012   # machine resumed from sleep/hibernate

# MSG addresses below this are clearly not real heap pointers; probing
# them would crash the process, so such messages are ignored upfront.
_MIN_VALID_MSG_ADDRESS = 0x10000


class TrayAndPowerFilter(QAbstractNativeEventFilter):
    """Keeps the tray icon alive after Explorer restarts and auto-reconnects
    the proxy after the machine wakes from sleep."""

    def __init__(self, on_taskbar_created, on_resume):
        super().__init__()
        self.on_taskbar_created = on_taskbar_created
        self.on_resume = on_resume

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            try:
                import ctypes
                import struct
                addr = int(message)
                if addr < _MIN_VALID_MSG_ADDRESS:
                    return False, 0
                data = (ctypes.c_char * 32).from_address(addr)
                _, msg, wparam, _ = struct.unpack_from("<QI4xQq", bytes(data))
                if msg == WM_TASKBARCREATED:
                    self.on_taskbar_created()
                elif msg == WM_POWERBROADCAST and wparam == PBT_APMRESUMESUSPEND:
                    self.on_resume()
            except (ValueError, OSError, AttributeError, TypeError,
                    struct.error) as e:
                log.debug("Ignoring malformed native message: %s", e)
        return False, 0


def initialize():
    """Windows startup init: logging, app user model id, excepthook.

    No-op on other platforms, matching the previous Linux entry point.
    """
    if not is_windows():
        return
    setup_logging()
    logging.getLogger("start_win").info("Launching Socksicle on Windows")
    set_app_user_model_id()
    install_excepthook()


def set_app_user_model_id():
    """Required for correct taskbar grouping and toast notifications."""
    if not is_windows():
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "socksicle.desktop")
    except (AttributeError, OSError) as e:
        log.warning("Failed to set AppUserModelID: %s", e)


def install_excepthook():
    """Route unhandled exceptions through logging and stderr."""
    if not is_windows():
        return

    def excepthook(exc_type, exc_value, exc_tb):
        logging.getLogger("unhandled").critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        try:
            if sys.stderr:
                traceback.print_exception(exc_type, exc_value, exc_tb)
        except Exception as e:
            log.debug("Failed to write exception to stderr: %s", e)

    sys.excepthook = excepthook


def desktop_file_name() -> str:
    """Windows uses the app id; Linux uses the .desktop entry name."""
    return "Socksicle" if is_windows() else "Socksicle.desktop"


def apply_high_dpi_policy(app):
    """Windows: PassThrough scale-factor rounding for the QApplication."""
    if not is_windows():
        return
    app.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)


def install_native_handlers(app, window):
    """Install the tray/power native event filter on Windows.

    Keeps a strong reference on the app so the filter lives for the whole
    session.  Returns the filter on Windows, None elsewhere.
    """
    if not is_windows():
        return None
    filter_ = TrayAndPowerFilter(
        on_taskbar_created=lambda: window.tray_icon.show(),
        on_resume=window.reconnect_after_resume,
    )
    app.installNativeEventFilter(filter_)
    app.native_filter = filter_  # keep a strong reference
    return filter_