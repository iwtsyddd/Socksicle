"""Entry-point tests for the single Socksicle entry point (main.py).

Complements test_platform_startup.py: verifies exit codes, the shared flow
order with a single provisioning pass, and -- with real platform functions
-- that Windows-specific startup only runs on Windows and Linux keeps its
exact previous behavior.
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main  # noqa: E402
from utils import platform_startup as ps  # noqa: E402
from utils.startup_utils import DECLINED_REASON  # noqa: E402


def _backend_ok():
    return SimpleNamespace(ok=True, reason="ok")


def _run_main(backend, exit_behavior=SystemExit):
    """Run main.main() with everything concrete mocked; sys.exit raises."""
    app_inst = mock.Mock()
    app_inst.exec.side_effect = exit_behavior or (lambda: 0)
    app_cls = mock.Mock(return_value=app_inst)
    window_inst = mock.Mock()
    window_cls = mock.Mock(return_value=window_inst)
    with mock.patch.object(main, "QApplication", app_cls), \
         mock.patch.object(main, "RoundedWindow", window_cls), \
         mock.patch.object(main, "QIcon"), \
         mock.patch.object(main, "get_app_dir",
                           return_value=Path.cwd() / "icon.png"), \
         mock.patch.object(main, "provision_backend", return_value=backend), \
         mock.patch.object(sys, "exit",
                           side_effect=SystemExit) as exit_mock:
        try:
            main.main()
        except SystemExit:
            pass
    return app_inst, window_inst, app_cls, window_cls, exit_mock


class ExitCodeTest(unittest.TestCase):
    """main.main() exits with the Qt event loop code or 1 on backend loss."""

    def test_success_uses_app_exec_code(self):
        app_inst = mock.Mock()
        app_inst.exec.return_value = 42
        with mock.patch.object(main, "QApplication",
                               return_value=app_inst), \
             mock.patch.object(main, "RoundedWindow",
                               return_value=mock.Mock()), \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "get_app_dir",
                               return_value=Path.cwd() / "icon.png"), \
             mock.patch.object(main, "provision_backend",
                               return_value=_backend_ok()), \
             mock.patch.object(main, "initialize"), \
             mock.patch.object(main, "apply_high_dpi_policy"), \
             mock.patch.object(main, "desktop_file_name",
                               return_value="Socksicle.desktop"), \
             mock.patch.object(main, "install_native_handlers"), \
             mock.patch.object(sys, "exit",
                               side_effect=SystemExit) as exit_mock:
            with self.assertRaises(SystemExit):
                main.main()
        exit_mock.assert_called_once_with(42)
        app_inst.exec.assert_called_once_with()

    def test_provisioning_failure_shows_dialog_and_exits_1(self):
        with mock.patch.object(main, "QApplication",
                               return_value=mock.Mock()), \
             mock.patch.object(main, "RoundedWindow") as window_cls, \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "provision_backend",
                               return_value=SimpleNamespace(
                                   ok=False, reason="boom")), \
             mock.patch.object(main, "show_provisioning_failure") as show, \
             mock.patch.object(main, "initialize"), \
             mock.patch.object(main, "apply_high_dpi_policy"), \
             mock.patch.object(main, "desktop_file_name"), \
             mock.patch.object(sys, "exit",
                               side_effect=SystemExit) as exit_mock:
            with self.assertRaises(SystemExit):
                main.main()
            exit_mock.assert_called_once_with(1)
            show.assert_called_once()
            window_cls.assert_not_called()

    def test_cancelled_provisioning_starts_without_backend(self):
        with mock.patch.object(main, "QApplication",
                               return_value=mock.Mock()), \
             mock.patch.object(main, "RoundedWindow") as window_cls, \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "provision_backend",
                               return_value=None), \
             mock.patch.object(main, "show_provisioning_failure") as show, \
             mock.patch.object(main, "initialize"), \
             mock.patch.object(main, "apply_high_dpi_policy"), \
             mock.patch.object(main, "desktop_file_name"), \
             mock.patch.object(main, "install_native_handlers"), \
             mock.patch.object(sys, "exit",
                               side_effect=SystemExit) as exit_mock:
            with self.assertRaises(SystemExit):
                main.main()
            show.assert_not_called()
            window_cls.assert_called_once()

    def test_declined_provisioning_starts_without_backend(self):
        with mock.patch.object(main, "QApplication",
                               return_value=mock.Mock()), \
             mock.patch.object(main, "RoundedWindow") as window_cls, \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "provision_backend",
                               return_value=SimpleNamespace(
                                   ok=False, reason=DECLINED_REASON)), \
             mock.patch.object(main, "show_provisioning_failure") as show, \
             mock.patch.object(main, "initialize"), \
             mock.patch.object(main, "apply_high_dpi_policy"), \
             mock.patch.object(main, "desktop_file_name"), \
             mock.patch.object(main, "install_native_handlers"), \
             mock.patch.object(sys, "exit",
                               side_effect=SystemExit) as exit_mock:
            with self.assertRaises(SystemExit):
                main.main()
            show.assert_not_called()
            window_cls.assert_called_once()


class SharedFlowOrderTest(unittest.TestCase):
    """The shared flow runs once, in order, with one provisioning pass."""

    def test_flow_order_and_single_provisioning(self):
        calls = []
        app_inst = mock.Mock()
        app_inst.exec.side_effect = lambda: calls.append("exec") or 0
        window_inst = mock.Mock()
        window_inst.show.side_effect = lambda: calls.append("show")
        with mock.patch.object(main, "QApplication",
                               return_value=app_inst), \
             mock.patch.object(main, "RoundedWindow",
                               side_effect=lambda: calls.append("create")
                               or window_inst), \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "get_app_dir",
                               return_value=Path.cwd() / "icon.png"), \
             mock.patch.object(main, "provision_backend",
                               side_effect=lambda: calls.append("provision")
                               or _backend_ok()) as provision, \
             mock.patch.object(main, "initialize",
                               side_effect=lambda: calls.append("init")), \
             mock.patch.object(main, "apply_high_dpi_policy",
                               side_effect=lambda *a: calls.append("high-dpi")), \
             mock.patch.object(main, "desktop_file_name",
                               side_effect=lambda: calls.append("desktop-file")
                               or "Socksicle.desktop"), \
             mock.patch.object(main, "install_native_handlers",
                               side_effect=lambda a, w: calls.append(
                                   "handlers")), \
             mock.patch.object(sys, "exit",
                               side_effect=SystemExit) as exit_mock:
            with self.assertRaises(SystemExit):
                main.main()
        self.assertEqual(calls, [
            "init", "high-dpi", "desktop-file", "provision",
            "create", "handlers", "show", "exec",
        ])
        provision.assert_called_once_with()
        exit_mock.assert_called_once_with(0)


@mock.patch.object(ps, "is_windows", return_value=False)
class LinuxPathTest(unittest.TestCase):
    """Real platform functions: Linux skips every Windows-only step."""

    def test_linux_flow_keeps_previous_behavior(self, _is_win):
        app_inst = mock.Mock(spec=[
            "setApplicationName", "setDesktopFileName", "setWindowIcon",
            "setHighDpiScaleFactorRoundingPolicy", "installNativeEventFilter",
            "setStyle", "setPalette", "exec",
        ])
        app_inst.exec.return_value = 0
        with mock.patch.object(main, "QApplication",
                               return_value=app_inst), \
             mock.patch.object(main, "RoundedWindow",
                               return_value=mock.Mock()), \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "get_app_dir",
                               return_value=Path.cwd() / "icon.png"), \
             mock.patch.object(main, "provision_backend",
                               return_value=_backend_ok()), \
             mock.patch.object(sys, "exit",
                               side_effect=SystemExit) as exit_mock:
            with self.assertRaises(SystemExit):
                main.main()
        exit_mock.assert_called_once_with(0)
        app_inst.setApplicationName.assert_called_once_with("Socksicle")
        app_inst.setDesktopFileName.assert_called_once_with(
            "Socksicle.desktop")
        app_inst.setHighDpiScaleFactorRoundingPolicy.assert_not_called()
        app_inst.installNativeEventFilter.assert_not_called()
        if sys.platform == "win32":
            app_inst.setStyle.assert_not_called()
            app_inst.setPalette.assert_not_called()
        else:
            app_inst.setStyle.assert_called_once_with("Fusion")
            app_inst.setPalette.assert_called_once()
        self.assertNotIn("native_filter", app_inst._mock_children)


class WindowsPathTest(unittest.TestCase):
    """Real platform functions: Windows applies all platform pieces."""

    @mock.patch.object(ps, "is_windows", return_value=True)
    def test_windows_flow_applies_windows_pieces(self, _is_win):
        app_inst = mock.Mock()
        app_inst.exec.return_value = 0
        window_inst = mock.Mock()
        with mock.patch.object(ps, "setup_logging"), \
             mock.patch.object(ps.logging, "getLogger"), \
             mock.patch.object(ps, "set_app_user_model_id"), \
             mock.patch.object(ps, "install_excepthook"), \
             mock.patch.object(main, "QApplication",
                               return_value=app_inst), \
             mock.patch.object(main, "RoundedWindow",
                               return_value=window_inst), \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "get_app_dir",
                               return_value=Path.cwd() / "icon.png"), \
             mock.patch.object(main, "provision_backend",
                               return_value=_backend_ok()), \
             mock.patch.object(sys, "exit",
                               side_effect=SystemExit) as exit_mock:
            with self.assertRaises(SystemExit):
                main.main()
        exit_mock.assert_called_once_with(0)
        app_inst.setDesktopFileName.assert_called_once_with("Socksicle")
        app_inst.installNativeEventFilter.assert_called_once()
        self.assertIsInstance(app_inst.native_filter,
                              ps.TrayAndPowerFilter)
        app_inst.native_filter.on_taskbar_created()
        window_inst.tray_icon.show.assert_called_once_with()
        app_inst.native_filter.on_resume()
        window_inst.reconnect_after_resume.assert_called_once_with()


class CLIMinimizedTest(unittest.TestCase):
    """Tests for --minimized / -m command line argument behavior in main.py."""

    def test_parse_args_flags(self):
        args_default = main.parse_args([])
        self.assertFalse(args_default.minimized)

        args_long = main.parse_args(["--minimized"])
        self.assertTrue(args_long.minimized)

        args_short = main.parse_args(["-m"])
        self.assertTrue(args_short.minimized)

    def test_minimized_with_tray_available_skips_window_show(self):
        app_inst = mock.Mock()
        app_inst.exec.return_value = 0
        window_inst = mock.Mock()

        with mock.patch.object(main, "QApplication", return_value=app_inst), \
             mock.patch.object(main, "RoundedWindow", return_value=window_inst), \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "get_app_dir", return_value=Path.cwd() / "icon.png"), \
             mock.patch.object(main, "provision_backend", return_value=_backend_ok()), \
             mock.patch.object(main, "initialize"), \
             mock.patch.object(main, "apply_high_dpi_policy"), \
             mock.patch.object(main, "desktop_file_name", return_value="Socksicle.desktop"), \
             mock.patch.object(main, "install_native_handlers"), \
             mock.patch.object(main.QSystemTrayIcon, "isSystemTrayAvailable", return_value=True), \
             mock.patch.object(sys, "exit", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                main.main(["--minimized"])

        window_inst.show.assert_not_called()
        app_inst.exec.assert_called_once()

    def test_minimized_without_tray_available_shows_window(self):
        app_inst = mock.Mock()
        app_inst.exec.return_value = 0
        window_inst = mock.Mock()

        with mock.patch.object(main, "QApplication", return_value=app_inst), \
             mock.patch.object(main, "RoundedWindow", return_value=window_inst), \
             mock.patch.object(main, "QIcon"), \
             mock.patch.object(main, "get_app_dir", return_value=Path.cwd() / "icon.png"), \
             mock.patch.object(main, "provision_backend", return_value=_backend_ok()), \
             mock.patch.object(main, "initialize"), \
             mock.patch.object(main, "apply_high_dpi_policy"), \
             mock.patch.object(main, "desktop_file_name", return_value="Socksicle.desktop"), \
             mock.patch.object(main, "install_native_handlers"), \
             mock.patch.object(main.QSystemTrayIcon, "isSystemTrayAvailable", return_value=False), \
             mock.patch.object(sys, "exit", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                main.main(["-m"])

        window_inst.show.assert_called_once()
        app_inst.exec.assert_called_once()


if __name__ == "__main__":
    unittest.main()