"""Focused tests for utils.platform_utils is_admin / elevate_restart platform guards.

All platform detection and subprocess activity is mocked; nothing is executed.
"""
import os
import sys
import unittest
from unittest import mock

from utils import platform_utils


@mock.patch("utils.platform_utils.sys.platform", "linux")
class LinuxIsAdminTest(unittest.TestCase):

    def test_is_admin_true_when_root(self):
        with mock.patch("utils.platform_utils.os.geteuid",
                        return_value=0, create=True):
            self.assertTrue(platform_utils.is_admin())

    def test_is_admin_false_when_not_root(self):
        with mock.patch("utils.platform_utils.os.geteuid",
                        return_value=1000, create=True):
            self.assertFalse(platform_utils.is_admin())

    def test_is_admin_false_when_no_geteuid(self):
        with mock.patch("utils.platform_utils.os.geteuid", create=True, new=None):
            self.assertFalse(platform_utils.is_admin())


@mock.patch("utils.platform_utils.sys.platform", "darwin")
class UnsupportedPlatformTest(unittest.TestCase):

    def test_is_admin_false_off_platform(self):
        self.assertFalse(platform_utils.is_admin())

    def test_elevate_restart_false_off_platform(self):
        self.assertFalse(platform_utils.elevate_restart())


@mock.patch("utils.platform_utils.sys.platform", "linux")
class LinuxElevateRestartTest(unittest.TestCase):

    def test_pkexec_used_when_available(self):
        exit_ = mock.Mock(side_effect=SystemExit(0))
        argv = ["/opt/socksicle/app.py", "--flag"]
        with mock.patch("shutil.which",
                        return_value="/usr/bin/pkexec"), \
             mock.patch("subprocess.Popen") as popen, \
             mock.patch.object(platform_utils.sys, "argv", argv), \
             mock.patch.object(platform_utils.sys, "executable",
                               "/usr/bin/python3"), \
             mock.patch.object(platform_utils.sys, "exit", exit_):
            with self.assertRaises(SystemExit):
                platform_utils.elevate_restart()
        popen.assert_called_once_with(
            ["pkexec", "/usr/bin/python3", argv[0], "--flag"])

    def test_sudo_fallback_when_pkexec_missing(self):
        exit_ = mock.Mock(side_effect=SystemExit(0))
        argv = ["/opt/socksicle/app.py"]
        def _which(cmd):
            return "/usr/bin/sudo" if cmd == "sudo" else None
        with mock.patch("shutil.which", side_effect=_which), \
             mock.patch("subprocess.Popen") as popen, \
             mock.patch.object(platform_utils.sys, "argv", argv), \
             mock.patch.object(platform_utils.sys, "executable",
                               "/usr/bin/python3"), \
             mock.patch.object(platform_utils.sys, "exit", exit_):
            with self.assertRaises(SystemExit):
                platform_utils.elevate_restart()
        popen.assert_called_once_with(
            ["sudo", "/usr/bin/python3", argv[0]])

    def test_returns_false_when_no_elevator(self):
        argv = ["/opt/socksicle/app.py"]
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("subprocess.Popen") as popen, \
             mock.patch.object(platform_utils.sys, "argv", argv), \
             mock.patch.object(platform_utils.sys, "executable",
                               "/usr/bin/python3"), \
             mock.patch.object(platform_utils.sys, "exit") as exit_:
            result = platform_utils.elevate_restart()
        self.assertFalse(result)
        popen.assert_not_called()
        exit_.assert_not_called()

    def test_sudo_fallback_when_pkexec_exec_fails(self):
        exit_ = mock.Mock(side_effect=SystemExit(0))
        argv = ["/opt/socksicle/app.py"]
        calls = []

        def _which(cmd):
            return f"/usr/bin/{cmd}"

        def _popen(args, **kwargs):
            calls.append(args)
            if args[0] == "pkexec":
                raise OSError("pkexec launch failed")
            return mock.Mock()

        with mock.patch("shutil.which", side_effect=_which), \
             mock.patch("subprocess.Popen", side_effect=_popen), \
             mock.patch.object(platform_utils.sys, "argv", argv), \
             mock.patch.object(platform_utils.sys, "executable",
                               "/usr/bin/python3"), \
             mock.patch.object(platform_utils.sys, "exit", exit_):
            with self.assertRaises(SystemExit):
                platform_utils.elevate_restart()
        self.assertEqual(calls[0][0], "pkexec")
        self.assertEqual(calls[1][0], "sudo")