"""Platform-specific startup behavior, isolated behind small functions.

The shared entry point (:mod:`main`) runs the same flow on every platform
and delegates the platform-specific pieces here:

    application start
      -> platform initialization (env, logging, user model id, excepthook)
      -> backend provisioning
      -> create main window
      -> install tray/power/network handlers if supported
      -> start Qt event loop

File logging and the unhandled-exception hook run on every platform so
runtime failures stay visible on all operating systems. Windows provides
high-DPI environment, AppUserModelID, tray persistence across Explorer restarts
(WM_TASKBARCREATED) and reconnect after sleep/hibernate resume (WM_POWERBROADCAST).
Linux provides D-Bus monitoring for system sleep/resume (systemd-logind PrepareForSleep)
and network state recovery (NetworkManager StateChanged).
Every platform-specific helper degrades to a safe no-op elsewhere.
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
from pathlib import Path
import traceback
from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Slot

from utils.platform_utils import is_linux, is_windows, setup_logging

log = logging.getLogger(__name__)

# Native event messages (WinUser.h)
WM_TASKBARCREATED = 0x0219      # Explorer restarted -> re-register tray icon
WM_POWERBROADCAST = 0x0218
PBT_APMRESUMESUSPEND = 0x0012   # machine resumed from sleep/hibernate

# MSG addresses below this are clearly not real heap pointers; probing
# them would crash the process, so such messages are ignored upfront.
_MIN_VALID_MSG_ADDRESS = 0x10000

# NetworkManager NMState enum values
NM_STATE_UNKNOWN = 0
NM_STATE_ASLEEP = 10
NM_STATE_DISCONNECTED = 20
NM_STATE_DISCONNECTING = 30
NM_STATE_CONNECTING = 40
NM_STATE_CONNECTED_LOCAL = 50
NM_STATE_CONNECTED_SITE = 60
NM_STATE_CONNECTED_GLOBAL = 70

# D-Bus interfaces and signals (Linux systemd-logind & NetworkManager)
LOGIN1_SERVICE = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
LOGIN1_INTERFACE = "org.freedesktop.login1.Manager"
LOGIN1_SIGNAL_PREPARE_FOR_SLEEP = "PrepareForSleep"

NM_SERVICE = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_INTERFACE = "org.freedesktop.NetworkManager"
NM_SIGNAL_STATE_CHANGED = "StateChanged"


def _subscribe_dbus_signal(bus, service: str, path: str, interface: str, name: str,
                           receiver: QObject, slot_fn, slot_name: str) -> bool:
    """Connect a D-Bus signal to a receiver slot, trying callable and named slot signatures."""
    try:
        res = bus.connect(service, path, interface, name, slot_fn)
        if res:
            return True
    except (TypeError, AttributeError, Exception) as e:
        log.debug("bus.connect with callable (%s) failed: %s", name, e)

    try:
        res = bus.connect(service, path, interface, name, receiver, slot_name)
        if res:
            return True
    except (TypeError, AttributeError, Exception) as e:
        log.debug("bus.connect with receiver/slot_name (%s) failed: %s", name, e)

    try:
        res = bus.connect(service, path, interface, name, receiver, slot_fn)
        if res:
            return True
    except (TypeError, AttributeError, Exception) as e:
        log.debug("bus.connect with receiver/slot_fn (%s) failed: %s", name, e)

    return False


class LinuxDBusPowerNetworkFilter(QObject):
    """Monitors system sleep/resume (systemd-logind) and network state (NetworkManager) on Linux via D-Bus."""

    def __init__(self, on_resume, on_network_change=None, parent=None, bus=None):
        super().__init__(parent)
        self.on_resume = on_resume
        self.on_network_change = on_network_change or on_resume
        self.is_sleeping = False
        self._last_nm_state = None
        self._bus = bus
        self._login1_connected = False
        self._nm_connected = False
        self.setup()

    @property
    def is_connected(self) -> bool:
        """True if at least one D-Bus signal subscription succeeded."""
        return self._login1_connected or self._nm_connected

    def setup(self) -> bool:
        """Connect to system bus and subscribe to systemd-logind and NetworkManager signals."""
        try:
            if self._bus is None:
                try:
                    from PySide6 import QtDBus
                    self._bus = QtDBus.QDBusConnection.systemBus()
                except (ImportError, AttributeError) as e:
                    log.warning("PySide6.QtDBus is not available: %s; Linux power/network monitoring disabled.", e)
                    return False

            if not hasattr(self._bus, "isConnected") or not self._bus.isConnected():
                log.warning("D-Bus system bus is not connected; Linux power/network monitoring disabled.")
                return False

            # Subscribe to systemd-logind PrepareForSleep(bool)
            try:
                self._login1_connected = _subscribe_dbus_signal(
                    self._bus,
                    LOGIN1_SERVICE,
                    LOGIN1_PATH,
                    LOGIN1_INTERFACE,
                    LOGIN1_SIGNAL_PREPARE_FOR_SLEEP,
                    self,
                    self.handle_prepare_for_sleep,
                    "handle_prepare_for_sleep",
                )
                if self._login1_connected:
                    log.info("Subscribed to systemd-logind PrepareForSleep D-Bus signal.")
                else:
                    log.warning("Failed to subscribe to systemd-logind PrepareForSleep D-Bus signal.")
            except Exception as e:
                log.warning("Error subscribing to systemd-logind PrepareForSleep: %s", e)

            # Subscribe to NetworkManager StateChanged(uint32)
            try:
                self._nm_connected = _subscribe_dbus_signal(
                    self._bus,
                    NM_SERVICE,
                    NM_PATH,
                    NM_INTERFACE,
                    NM_SIGNAL_STATE_CHANGED,
                    self,
                    self.handle_nm_state_changed,
                    "handle_nm_state_changed",
                )
                if self._nm_connected:
                    log.info("Subscribed to NetworkManager StateChanged D-Bus signal.")
                else:
                    log.warning("Failed to subscribe to NetworkManager StateChanged D-Bus signal.")
            except Exception as e:
                log.warning("Error subscribing to NetworkManager StateChanged: %s", e)

            return self.is_connected

        except Exception as e:
            log.warning("Unexpected error initializing Linux D-Bus listener: %s", e)
            return False

    @Slot(bool)
    def handle_prepare_for_sleep(self, sleeping: bool):
        """Handle systemd-logind PrepareForSleep(bool) signal.

        Args:
            sleeping: True when entering sleep/hibernate, False when waking up.
        """
        sleeping_bool = bool(sleeping)
        self.is_sleeping = sleeping_bool
        if sleeping_bool:
            log.info("System preparing for sleep...")
        else:
            log.info("System resumed from sleep, triggering proxy reconnect...")
            if callable(self.on_resume):
                try:
                    self.on_resume()
                except Exception as e:
                    log.error("Error in on_resume callback: %s", e)

    @Slot(int)
    def handle_nm_state_changed(self, state: int):
        """Handle NetworkManager StateChanged(uint32) signal.

        Args:
            state: NetworkManager NMState enum integer.
        """
        try:
            state_int = int(state)
        except (ValueError, TypeError):
            log.debug("Ignoring invalid NetworkManager state value: %r", state)
            return

        prev_state = self._last_nm_state
        self._last_nm_state = state_int

        if state_int == NM_STATE_CONNECTED_GLOBAL:
            log.info("Network connectivity globally restored (NM_STATE_CONNECTED_GLOBAL=%d), triggering reconnect...", state_int)
            if callable(self.on_network_change):
                try:
                    self.on_network_change()
                except Exception as e:
                    log.error("Error in on_network_change callback: %s", e)
        elif state_int == NM_STATE_DISCONNECTED:
            log.info("Network disconnected (NM_STATE_DISCONNECTED=%d)", state_int)
        elif state_int == NM_STATE_CONNECTING:
            log.debug("Network connecting (NM_STATE_CONNECTING=%d)...", state_int)
        elif state_int == NM_STATE_ASLEEP:
            log.debug("NetworkManager asleep (NM_STATE_ASLEEP=%d)", state_int)
        else:
            log.debug("NetworkManager state changed: %d (previous: %s)", state_int, prev_state)

    def disconnect_signals(self):
        """Disconnect D-Bus signal listeners if connected."""
        if self._bus is not None and hasattr(self._bus, "disconnect"):
            if self._login1_connected:
                try:
                    self._bus.disconnect(
                        LOGIN1_SERVICE,
                        LOGIN1_PATH,
                        LOGIN1_INTERFACE,
                        LOGIN1_SIGNAL_PREPARE_FOR_SLEEP,
                        self.handle_prepare_for_sleep,
                    )
                except Exception:
                    pass
                self._login1_connected = False
            if self._nm_connected:
                try:
                    self._bus.disconnect(
                        NM_SERVICE,
                        NM_PATH,
                        NM_INTERFACE,
                        NM_SIGNAL_STATE_CHANGED,
                        self.handle_nm_state_changed,
                    )
                except Exception:
                    pass
                self._nm_connected = False


# Alias for compatibility / alternative naming
LinuxDBusFilter = LinuxDBusPowerNetworkFilter


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
    """Per-platform startup init.

    Logging and the unhandled-exception hook run on every platform; the
    AppUserModelID is set on Windows only.
    """
    setup_logging()
    logging.getLogger("startup").info(
        "Launching Socksicle on %s",
        "Windows" if is_windows() else "Linux",
    )
    set_app_user_model_id()
    install_excepthook()
    # Emergency crash recovery: clean any stale Kill Switch firewall rules from previous taskkill crashes
    try:
        from utils.killswitch import KillSwitchManager
        KillSwitchManager.get_instance().clean_stale_rules()
    except Exception as e:
        log.debug("Startup stale rule cleanup skipped: %s", e)


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
    """Route unhandled exceptions through logging and stderr on all platforms."""

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


def apply_high_dpi_policy(app=None):
    """Windows: PassThrough scale-factor rounding for the QApplication."""
    if not is_windows():
        return
    if app is not None and hasattr(app, "setHighDpiScaleFactorRoundingPolicy"):
        app.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    else:
        try:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        except Exception:
            pass


def install_native_handlers(app, window):
    """Install platform-specific event handlers (Windows native messages or Linux D-Bus).

    On Windows: installs TrayAndPowerFilter via QAbstractNativeEventFilter for
    Explorer restarts (WM_TASKBARCREATED) and sleep resume (WM_POWERBROADCAST).
    On Linux: installs LinuxDBusPowerNetworkFilter for systemd-logind sleep/wake
    signals and NetworkManager state changes.

    Keeps a strong reference on the app so the filter lives for the whole session.
    Returns the active filter/listener object, or None if unsupported/unavailable.
    """
    if is_windows():
        filter_ = TrayAndPowerFilter(
            on_taskbar_created=lambda: window.tray_icon.show(),
            on_resume=window.reconnect_after_resume,
        )
        app.installNativeEventFilter(filter_)
        app.native_filter = filter_  # keep a strong reference
        return filter_

    if is_linux():
        try:
            dbus_filter = LinuxDBusPowerNetworkFilter(
                on_resume=window.reconnect_after_resume,
                on_network_change=window.reconnect_after_resume,
            )
            try:
                app.native_filter = dbus_filter  # keep a strong reference
            except AttributeError:
                pass
            return dbus_filter
        except Exception as e:
            log.warning("Failed to initialize Linux D-Bus listener: %s", e)
            return None

    return None


def get_autostart_desktop_path() -> Path:
    """Path to the user's XDG autostart desktop entry for Socksicle on Linux."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else (Path.home() / ".config")
    return base / "autostart" / "socksicle.desktop"


def is_autostart_enabled() -> bool:
    """Check if Socksicle autostart is enabled on the current platform.

    On Windows: checks HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run for 'Socksicle'.
    On Linux: checks ~/.config/autostart/socksicle.desktop exists and is not disabled.
    """
    if is_windows():
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            )
            try:
                val, _ = winreg.QueryValueEx(key, "Socksicle")
                return bool(val)
            finally:
                winreg.CloseKey(key)
        except (OSError, Exception):
            return False

    elif is_linux():
        path = get_autostart_desktop_path()
        if not path.is_file():
            return False
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            for line in content.splitlines():
                clean = line.strip().lower()
                if clean in ("hidden=true", "x-gnome-autostart-enabled=false"):
                    return False
            return True
        except Exception as e:
            log.debug("Failed to read autostart desktop file: %s", e)
            return False

    return False


def set_autostart(enable: bool, app_path: str | None = None) -> bool:
    """Enable or disable autostart on system boot for the current platform.

    Args:
        enable: True to enable autostart (with --minimized), False to disable.
        app_path: Optional custom executable path or command line.

    Returns:
        True if configuration succeeded, False on error.
    """
    if is_windows():
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ,
            )
            try:
                if enable:
                    if app_path:
                        exec_cmd = app_path if "--minimized" in app_path else f'"{app_path}" --minimized'
                    elif getattr(sys, "frozen", False):
                        exec_cmd = f'"{sys.executable}" --minimized'
                    else:
                        main_script = Path(sys.argv[0]).resolve()
                        exec_cmd = f'"{sys.executable}" "{main_script}" --minimized'
                    winreg.SetValueEx(key, "Socksicle", 0, winreg.REG_SZ, exec_cmd)
                    log.info("Enabled Windows autostart: %s", exec_cmd)
                    return True
                else:
                    try:
                        winreg.DeleteValue(key, "Socksicle")
                        log.info("Disabled Windows autostart.")
                    except FileNotFoundError:
                        pass
                    return True
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            log.warning("Failed to configure Windows autostart: %s", e)
            return False

    elif is_linux():
        path = get_autostart_desktop_path()
        try:
            if enable:
                if app_path:
                    exec_cmd = app_path if "--minimized" in app_path else f"{app_path} --minimized"
                elif getattr(sys, "frozen", False):
                    exec_cmd = f"{sys.executable} --minimized"
                else:
                    main_script = Path(sys.argv[0]).resolve()
                    exec_cmd = f"{sys.executable} {main_script} --minimized"

                path.parent.mkdir(parents=True, exist_ok=True)
                desktop_entry = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=Socksicle\n"
                    "Comment=Cross-platform Shadowsocks/TwinSock proxy client\n"
                    f"Exec={exec_cmd}\n"
                    "Icon=socksicle\n"
                    "Terminal=false\n"
                    "Categories=Network;Proxy;\n"
                    "StartupNotify=false\n"
                    "X-GNOME-Autostart-enabled=true\n"
                )
                path.write_text(desktop_entry, encoding="utf-8")
                log.info("Created Linux XDG autostart desktop entry at %s (Exec=%s)", path, exec_cmd)
                return True
            else:
                if path.exists():
                    path.unlink(missing_ok=True)
                    log.info("Removed Linux XDG autostart desktop entry at %s", path)
                return True
        except Exception as e:
            log.warning("Failed to configure Linux XDG autostart: %s", e)
            return False

    return False