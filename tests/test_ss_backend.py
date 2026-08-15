"""Tests for utils.ss_backend (target detection, sslocal discovery, usability)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from utils import platform_utils, ss_backend


def _magic_for_this_platform():
    if sys.platform == "win32":
        return b"MZ"
    if sys.platform == "darwin":
        return b"\xfe\xed\xfa\xcf"
    return b"\x7fELF"


def _make_file(path, magic=None, size=ss_backend.MIN_PLAUSIBLE_SIZE + 1,
               executable=True):
    """Create a fake executable file: correct magic + plausible size."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    magic = magic if magic is not None else _magic_for_this_platform()
    payload = magic + b"\x00" * (size - len(magic))
    path.write_bytes(payload)
    if executable and os.name != "nt":
        path.chmod(0o755)
    return path


class DetectTargetTest(unittest.TestCase):

    def test_windows_x64(self):
        self.assertEqual(
            ss_backend._detect_target("win32", "AMD64"), ss_backend.WINDOWS_X64)
        self.assertEqual(
            ss_backend._detect_target("win32", "x86_64"), ss_backend.WINDOWS_X64)

    def test_linux_x64(self):
        self.assertEqual(
            ss_backend._detect_target("linux", "x86_64"), ss_backend.LINUX_X64)
        self.assertEqual(
            ss_backend._detect_target("linux", "amd64"), ss_backend.LINUX_X64)

    def test_linux_arm64(self):
        self.assertEqual(
            ss_backend._detect_target("linux", "aarch64"), ss_backend.LINUX_ARM64)
        self.assertEqual(
            ss_backend._detect_target("linux", "ARM64"), ss_backend.LINUX_ARM64)

    def test_macos_x64(self):
        self.assertEqual(
            ss_backend._detect_target("darwin", "x86_64"), ss_backend.MACOS_X64)

    def test_macos_arm64(self):
        self.assertEqual(
            ss_backend._detect_target("darwin", "arm64"), ss_backend.MACOS_ARM64)

    def test_unsupported_architectures(self):
        for sys_platform, machine in [
            ("win32", "ARM64"),
            ("win32", "i686"),
            ("win32", "not-a-cpu"),
            ("linux", "i686"),
            ("linux", "armv7l"),
            ("linux", "riscv64"),
            ("linux", "loongarch64"),
            ("darwin", "powerpc"),
            ("darwin", ""),
        ]:
            with self.subTest(sys_platform=sys_platform, machine=machine):
                with self.assertRaises(ValueError):
                    ss_backend._detect_target(sys_platform, machine)

    def test_windows_arm64_rejected_explicitly(self):
        with self.assertRaisesRegex(ValueError, "Windows ARM64 is not supported"):
            ss_backend._detect_target("win32", "ARM64")

    def test_unsupported_platform(self):
        for sys_platform in ("freebsd", "cygwin", "java"):
            with self.subTest(sys_platform=sys_platform):
                with self.assertRaises(ValueError):
                    ss_backend._detect_target(sys_platform, "x86_64")

    @mock.patch("utils.ss_backend._platform.machine", return_value="AMD64")
    @mock.patch("utils.ss_backend.sys.platform", "win32")
    def test_detect_target_public_wrapper(self, _machine):
        self.assertEqual(
            ss_backend.detect_target(), ss_backend.WINDOWS_X64)
        self.assertEqual(_machine.call_count, 1)


class FindSSLocalTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app_bin = self.root / "app" / "bin"
        self.config_bin = self.root / "config" / "bin"
        self.path_dir = self.root / "path"
        self.path_dir.mkdir(parents=True)
        self.app_bin_path = self.app_bin / ("sslocal.exe" if sys.platform == "win32" else "sslocal")
        self.config_bin_path = self.config_bin / self.app_bin_path.name

        patchers = [
            mock.patch.object(ss_backend, "get_app_dir",
                              return_value=self.root / "app"),
            mock.patch.object(ss_backend, "get_config_dir",
                              return_value=self.root / "config"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def _patch_which(self, value):
        p = mock.patch.object(ss_backend.shutil, "which", return_value=value)
        p.start()
        self.addCleanup(p.stop)

    def test_app_bin_preferred(self):
        expected = _make_file(self.app_bin_path)
        _make_file(self.config_bin_path)
        _make_file(self.path_dir / self.app_bin_path.name)
        self._patch_which(str(self.path_dir / self.app_bin_path.name))
        self.assertEqual(ss_backend.find_sslocal(), expected)

    def test_config_bin_fallback(self):
        _make_file(self.app_bin_path, magic=b"nope",
                   size=ss_backend.MIN_PLAUSIBLE_SIZE + 1)  # invalid app candidate
        expected = _make_file(self.config_bin_path)
        _make_file(self.path_dir / self.app_bin_path.name)
        self._patch_which(str(self.path_dir / self.app_bin_path.name))
        self.assertEqual(ss_backend.find_sslocal(), expected)

    def test_path_fallback(self):
        path_file = _make_file(self.path_dir / self.app_bin_path.name)
        self._patch_which(str(path_file))
        self.assertEqual(ss_backend.find_sslocal(), path_file)

    def test_missing_sslocal(self):
        self._patch_which(None)
        self.assertIsNone(ss_backend.find_sslocal())

    def test_invalid_app_candidate_skipped(self):
        _make_file(self.app_bin_path, magic=b"nope",
                   size=ss_backend.MIN_PLAUSIBLE_SIZE + 1)
        expected = _make_file(self.config_bin_path)
        self._patch_which(None)
        self.assertEqual(ss_backend.find_sslocal(), expected)

    def test_all_candidates_invalid_returns_none(self):
        _make_file(self.app_bin_path, magic=b"nope",
                   size=ss_backend.MIN_PLAUSIBLE_SIZE + 1)
        _make_file(self.config_bin_path, magic=b"ZZZZ",
                   size=ss_backend.MIN_PLAUSIBLE_SIZE + 1)
        self._patch_which(None)
        self.assertIsNone(ss_backend.find_sslocal())

    def test_too_small_file_skipped(self):
        _make_file(self.app_bin_path, size=1000)
        self._patch_which(None)
        self.assertIsNone(ss_backend.find_sslocal())

    @unittest.skipIf(os.name != "nt",
                     "flat file and engine subdir share a name only on Windows "
                     "(app/bin/sslocal vs app/bin/sslocal/)")
    def test_flat_app_bin_preferred_over_subdir(self):
        expected = _make_file(self.app_bin_path)
        _make_file(self.root / "app" / "bin" / "sslocal" / self.app_bin_path.name)
        self._patch_which(None)
        self.assertEqual(ss_backend.find_sslocal(), expected)

    def test_app_bin_subdir_found(self):
        expected = _make_file(self.root / "app" / "bin" / "sslocal"
                              / self.app_bin_path.name)
        self._patch_which(None)
        self.assertEqual(ss_backend.find_sslocal(), expected)

    def test_config_bin_subdir_found(self):
        expected = _make_file(self.root / "config" / "bin" / "sslocal"
                              / self.app_bin_path.name)
        self._patch_which(None)
        self.assertEqual(ss_backend.find_sslocal(), expected)

    @unittest.skipIf(os.name == "nt", "exec bit is a POSIX concept")
    def test_nonexecutable_skipped_on_posix(self):
        _make_file(self.app_bin_path, executable=False)
        self._patch_which(None)
        self.assertIsNone(ss_backend.find_sslocal())


class IsUsableTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _empty_run(self, returncode=0):
        run = mock.Mock(return_value=SimpleNamespace(returncode=returncode))
        p = mock.patch.object(ss_backend.subprocess, "run", run)
        p.start()
        self.addCleanup(p.stop)
        return run

    def test_no_path(self):
        result = ss_backend.is_usable(None)
        self.assertFalse(result.usable)
        self.assertIn("No sslocal path", result.reason)

    def test_missing_file(self):
        result = ss_backend.is_usable(self.dir / "sslocal")
        self.assertFalse(result.usable)
        self.assertIn("Not a file", result.reason)

    def test_too_small(self):
        path = _make_file(self.dir / "sslocal", size=1000)
        result = ss_backend.is_usable(path)
        self.assertFalse(result.usable)
        self.assertIn("stub", result.reason)

    def test_wrong_format(self):
        path = _make_file(self.dir / "sslocal", magic=b"nope",
                          size=ss_backend.MIN_PLAUSIBLE_SIZE + 1)
        result = ss_backend.is_usable(path)
        self.assertFalse(result.usable)
        self.assertIn("recognizable", result.reason)

    @unittest.skipIf(os.name == "nt", "exec bit is a POSIX concept")
    def test_not_executable_on_posix(self):
        path = _make_file(self.dir / "sslocal", executable=False)
        result = ss_backend.is_usable(path)
        self.assertFalse(result.usable)
        self.assertIn("Not executable", result.reason)

    def test_valid_format_and_version_success(self):
        path = _make_file(self.dir / "sslocal")
        run = self._empty_run(returncode=0)
        result = ss_backend.is_usable(path)
        self.assertTrue(result.usable)
        self.assertEqual(result.reason, "")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], str(path))
        self.assertEqual(run.call_args.args[0][1], "--version")

    def test_version_failure(self):
        path = _make_file(self.dir / "sslocal")
        self._empty_run(returncode=1)
        result = ss_backend.is_usable(path)
        self.assertFalse(result.usable)
        self.assertIn("exited with code 1", result.reason)

    def test_version_raises_oserror(self):
        path = _make_file(self.dir / "sslocal")
        p = mock.patch.object(ss_backend.subprocess, "run",
                              side_effect=FileNotFoundError("missing"))
        p.start()
        self.addCleanup(p.stop)
        result = ss_backend.is_usable(path)
        self.assertFalse(result.usable)
        self.assertIn("Could not run", result.reason)

    def test_version_timeout(self):
        path = _make_file(self.dir / "sslocal")
        p = mock.patch.object(
            ss_backend.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(
                cmd=f"{path} --version", timeout=10))
        p.start()
        self.addCleanup(p.stop)
        result = ss_backend.is_usable(path)
        self.assertFalse(result.usable)
        self.assertIn("Could not run", result.reason)

    def test_windows_creation_flags(self):
        path = _make_file(self.dir / "sslocal")
        run = self._empty_run(returncode=0)
        ss_backend.is_usable(path)
        expected = (ss_backend.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        self.assertEqual(run.call_args.kwargs.get("creationflags"), expected)


class PlatformUtilsDelegationTest(unittest.TestCase):

    def test_find_sslocal_delegates_to_ss_backend(self):
        expected = Path("C:/fake/sslocal.exe")
        with mock.patch.object(ss_backend, "find_sslocal",
                               return_value=expected) as backend_find:
            self.assertEqual(platform_utils.find_sslocal(), expected)
            backend_find.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()