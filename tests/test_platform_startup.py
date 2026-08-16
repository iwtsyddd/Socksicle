"""Unit tests for utils.platform_startup's platform-specific pieces.

Complements the flow-level coverage in test_entry_points.py: native message
parsing of the tray/power filter, Windows-only environment setup, high-DPI
rounding policy application, native handler wiring, and the unhandled-
exception hook behavior.
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils import platform_startup  # noqa: E402
from utils.platform_startup import TrayAndPowerFilter  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

_HIGH_DPI_KEYS = ("QT_ENABLE_HIGHDPI_SCALING", "QT_AUTO_SCREEN_SCALE_FACTOR",
                  "QT_SCALE_FACTOR_ROUNDING_POLICY")


class ImportTimeEnvironmentTest(unittest.TestCase):
    """The Windows high-DPI environment is applied at import time only."""

    def test_high_dpi_env_applied_before_qt_initialises(self):
        pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = ("import os, utils.platform_startup; "
                "print({k: os.environ.get(k) for k in ("
                "'QT_ENABLE_HIGHDPI_SCALING', 'QT_AUTO_SCREEN_SCALE_FACTOR', "
                "'QT_SCALE_FACTOR_ROUNDING_POLICY')})")
        out = subprocess.check_output(
            [sys.executable, "-c", code],
            cwd=pkg,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            text=True,
        )
        values = eval(out.strip())
        if sys.platform == "win32":
            self.assertEqual(values["QT_ENABLE_HIGHDPI_SCALING"], "1")
            self.assertEqual(values["QT_AUTO_SCREEN_SCALE_FACTOR"], "1")
            self.assertEqual(values["QT_SCALE_FACTOR_ROUNDING_POLICY"],
                             "PassThrough")
        else:
            for key in _HIGH_DPI_KEYS:
                self.assertIsNone(values[key])


class TrayAndPowerFilterTest(unittest.TestCase):
    """Native message parsing: taskbar-create and power-resume events."""

    def setUp(self):
        self.taskbar = mock.Mock()
        self.resume = mock.Mock()
        self.filter_ = TrayAndPowerFilter(
            on_taskbar_created=self.taskbar, on_resume=self.resume)

    def _make_msg(self, msg=0, wparam=0):
        """Create a fake Windows MSG struct as an int-addressable object."""
        import ctypes
        import struct
        buf = ctypes.create_string_buffer(32)
        struct.pack_into("<QI4xQq", buf, 0, 0, msg, wparam, 0)

        class _MsgAddr(int):
            _kept = []
            def __new__(cls, address, _keep=buf):
                cls._kept.append(_keep)
                return super().__new__(cls, address)

        return _MsgAddr(ctypes.addressof(buf))

    def test_taskbar_created_event_reregisters_tray(self):
        buf = self._make_msg(msg=platform_startup.WM_TASKBARCREATED)
        self.filter_.nativeEventFilter(b"windows_generic_MSG", buf)
        self.taskbar.assert_called_once_with()
        self.resume.assert_not_called()

    def test_power_resume_event_reconnects(self):
        buf = self._make_msg(
            msg=platform_startup.WM_POWERBROADCAST,
            wparam=platform_startup.PBT_APMRESUMESUSPEND)
        self.filter_.nativeEventFilter(b"windows_generic_MSG", buf)
        self.resume.assert_called_once_with()
        self.taskbar.assert_not_called()

    def test_power_event_with_other_wparam_is_ignored(self):
        buf = self._make_msg(msg=platform_startup.WM_POWERBROADCAST, wparam=0)
        self.filter_.nativeEventFilter(b"windows_generic_MSG", buf)
        self.resume.assert_not_called()
        self.taskbar.assert_not_called()

    def test_non_windows_event_type_is_ignored(self):
        buf = self._make_msg(msg=platform_startup.WM_TASKBARCREATED)
        self.filter_.nativeEventFilter(b"generic", buf)
        self.taskbar.assert_not_called()
        self.resume.assert_not_called()

    def test_malformed_message_does_not_crash(self):
        for message in (b"\x00" * 4, 12345):
            result = self.filter_.nativeEventFilter(
                b"windows_generic_MSG", message)
            self.assertEqual(result, (False, 0))
        self.taskbar.assert_not_called()
        self.resume.assert_not_called()

    def test_returns_false_to_forward_event_to_qt(self):
        buf = self._make_msg(msg=platform_startup.WM_TASKBARCREATED)
        result = self.filter_.nativeEventFilter(
            b"windows_generic_MSG", buf)
        self.assertEqual(result, (False, 0))


class ApplyHighDpiPolicyTest(unittest.TestCase):

    def test_windows_applies_passthrough_rounding_policy(self):
        app = mock.Mock()
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=True):
            result = platform_startup.apply_high_dpi_policy(app)
        self.assertIsNone(result)
        app.setHighDpiScaleFactorRoundingPolicy.assert_called_once_with(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    def test_linux_skips_rounding_policy(self):
        app = mock.Mock()
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=False):
            platform_startup.apply_high_dpi_policy(app)
        app.setHighDpiScaleFactorRoundingPolicy.assert_not_called()


class InstallNativeHandlersTest(unittest.TestCase):
    """Tray/power native handlers are wired only on Windows."""

    def test_windows_installs_tray_and_power_filter(self):
        app = mock.Mock()
        window = mock.Mock()
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=True):
            filter_ = platform_startup.install_native_handlers(app, window)
        self.assertIsInstance(filter_, TrayAndPowerFilter)
        app.installNativeEventFilter.assert_called_once_with(filter_)
        self.assertIs(app.native_filter, filter_)
        filter_.on_taskbar_created()
        window.tray_icon.show.assert_called_once_with()
        filter_.on_resume()
        window.reconnect_after_resume.assert_called_once_with()

    def test_linux_skips_native_handlers(self):
        app = mock.Mock()
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=False):
            filter_ = platform_startup.install_native_handlers(
                app, mock.Mock())
        self.assertIsNone(filter_)
        app.installNativeEventFilter.assert_not_called()
        self.assertNotIn("native_filter", app._mock_children)


class ExcepthookTest(unittest.TestCase):
    """The unhandled-exception hook runs on every platform and logs safely."""

    def setUp(self):
        self._original_hook = sys.excepthook
        self.addCleanup(self._restore_hook)

    def _restore_hook(self):
        sys.excepthook = self._original_hook

    def test_windows_installs_hook_that_logs_and_prints(self):
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=True):
            platform_startup.install_excepthook()
        self.assertIsNot(sys.excepthook, self._original_hook)

        logger = mock.Mock()
        traceback_print = mock.Mock()
        with mock.patch.object(platform_startup.logging, "getLogger",
                               return_value=logger), \
             mock.patch.object(platform_startup.traceback,
                               "print_exception",
                               side_effect=traceback_print):
            sys.excepthook(ValueError, ValueError("boom"), None)
        logger.critical.assert_called_once()
        self.assertIn("exc_info", logger.critical.call_args.kwargs)
        traceback_print.assert_called_once()

    def test_linux_installs_hook_that_logs_and_prints(self):
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=False):
            platform_startup.install_excepthook()
        self.assertIsNot(sys.excepthook, self._original_hook)

        logger = mock.Mock()
        traceback_print = mock.Mock()
        with mock.patch.object(platform_startup.logging, "getLogger",
                               return_value=logger), \
             mock.patch.object(platform_startup.traceback,
                               "print_exception",
                               side_effect=traceback_print):
            sys.excepthook(ValueError, ValueError("boom"), None)
        logger.critical.assert_called_once()
        self.assertIn("exc_info", logger.critical.call_args.kwargs)
        traceback_print.assert_called_once()

    def test_hook_tolerates_stderr_failure(self):
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=True):
            platform_startup.install_excepthook()
        with mock.patch.object(platform_startup.logging, "getLogger"), \
             mock.patch.object(platform_startup.traceback,
                               "print_exception",
                               side_effect=RuntimeError("stderr gone")):
            sys.excepthook(ValueError, ValueError("boom"), None)  # no raise


class DesktopFileNameTest(unittest.TestCase):

    def test_windows_uses_app_id_name(self):
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=True):
            self.assertEqual(platform_startup.desktop_file_name(),
                             "Socksicle")

    def test_linux_uses_desktop_entry_name(self):
        with mock.patch.object(platform_startup, "is_windows",
                               return_value=False):
            self.assertEqual(platform_startup.desktop_file_name(),
                             "Socksicle.desktop")


if __name__ == "__main__":
    unittest.main()