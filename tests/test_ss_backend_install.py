"""Tests for utils.ss_backend provisioning (download, probe, install).

All network access is mocked; nothing is downloaded during tests.
"""
import io
import os
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from utils import ss_backend


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _platform_magic():
    if ss_backend.is_windows():
        return b"MZ"
    if sys.platform == "darwin":
        return b"\xfe\xed\xfa\xcf"
    return b"\x7fELF"


def _sslocal_bytes():
    magic = _platform_magic()
    return magic + b"\x00" * (ss_backend.MIN_PLAUSIBLE_SIZE + 1 - len(magic))


def _archive_bytes(files):
    """Build the archive format used by the current platform."""
    if ss_backend.is_windows():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in files.items():
                zf.writestr(name, data)
        return buf.getvalue()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _archive_name(target):
    suffix = "zip" if "windows" in target else "tar.xz"
    return f"shadowsocks-{ss_backend.SSLOCAL_VERSION}.{target}.{suffix}"


def _sslocal_member_name():
    return "sslocal.exe" if ss_backend.is_windows() else "sslocal"


class InstallTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config_dir = self.root / "config"
        self.bin_dir = self.config_dir / "bin"
        self.managed = self.bin_dir / ("sslocal.exe" if ss_backend.is_windows()
                                       else "sslocal")
        p = mock.patch.object(ss_backend, "get_config_dir",
                              return_value=self.config_dir)
        p.start()
        self.addCleanup(p.stop)
        probe = mock.patch.object(ss_backend, "_probe_range_support",
                                  return_value=None)
        probe.start()
        self.addCleanup(probe.stop)

    def _patch_urlopen(self, responses):
        m = mock.Mock(side_effect=responses)
        p = mock.patch.object(ss_backend.urllib.request, "urlopen", m)
        p.start()
        self.addCleanup(p.stop)
        return m

    def _patch_run(self, returncode=0):
        m = mock.Mock(return_value=SimpleNamespace(returncode=returncode))
        p = mock.patch.object(ss_backend.subprocess, "run", m)
        p.start()
        self.addCleanup(p.stop)
        return m

    def _success_responses(self, archive=None):
        archive = archive or _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        return [FakeResponse(archive)]

    def _bin_contents(self):
        if not self.bin_dir.exists():
            return {}
        return {p.name: p.read_bytes() for p in self.bin_dir.iterdir()}

    def _urls_called(self, mock_urlopen):
        return [call.args[0].full_url for call in mock_urlopen.call_args_list]


class ArtifactNameTest(unittest.TestCase):

    def test_windows_x64_artifact(self):
        self.assertEqual(
            ss_backend.artifact_filename(ss_backend.SSLOCAL_VERSION,
                                         ss_backend.WINDOWS_X64),
            "shadowsocks-v1.24.0.x86_64-pc-windows-msvc.zip")

    def test_linux_artifacts(self):
        self.assertEqual(
            ss_backend.artifact_filename(ss_backend.SSLOCAL_VERSION,
                                         ss_backend.LINUX_X64),
            "shadowsocks-v1.24.0.x86_64-unknown-linux-musl.tar.xz")
        self.assertEqual(
            ss_backend.artifact_filename(ss_backend.SSLOCAL_VERSION,
                                         ss_backend.LINUX_ARM64),
            "shadowsocks-v1.24.0.aarch64-unknown-linux-musl.tar.xz")

    def test_macos_artifacts(self):
        self.assertEqual(
            ss_backend.artifact_filename(ss_backend.SSLOCAL_VERSION,
                                         ss_backend.MACOS_X64),
            "shadowsocks-v1.24.0.x86_64-apple-darwin.tar.xz")
        self.assertEqual(
            ss_backend.artifact_filename(ss_backend.SSLOCAL_VERSION,
                                         ss_backend.MACOS_ARM64),
            "shadowsocks-v1.24.0.aarch64-apple-darwin.tar.xz")


class InstallTest(InstallTestCase):

    def test_successful_installation(self):
        urlopen = self._patch_urlopen(self._success_responses())
        self._patch_run(returncode=0)

        result = ss_backend.install_sslocal()

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.path, self.managed)
        self.assertTrue(self.managed.is_file())
        self.assertEqual(self.managed.read_bytes(), _sslocal_bytes())
        if os.name != "nt":
            self.assertTrue(os.access(self.managed, os.X_OK))

        urls = self._urls_called(urlopen)
        self.assertEqual(urls, [
            f"{ss_backend.RELEASE_BASE_URL}/{ss_backend.SSLOCAL_VERSION}/"
            f"{_archive_name(ss_backend.detect_target())}",
        ])

        self.assertEqual(self._bin_contents().keys(),
                         {self.managed.name, ss_backend.VERSION_MARKER_NAME})

    def test_version_marker(self):
        self._patch_urlopen(self._success_responses())
        self._patch_run(returncode=0)
        result = ss_backend.install_sslocal()
        self.assertTrue(result.ok, result.reason)
        marker = self.bin_dir / ss_backend.VERSION_MARKER_NAME
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.read_text(encoding="utf-8").strip(),
                         ss_backend.SSLOCAL_VERSION)
        self.assertEqual(ss_backend.installed_version(),
                         ss_backend.SSLOCAL_VERSION)

    def test_network_failure(self):
        self._patch_urlopen(urllib.error.URLError("boom"))

        result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertIn("Download failed", result.reason)
        self.assertEqual(self._bin_contents(), {})

    def test_http_failure_on_archive(self):
        url = f"{ss_backend.RELEASE_BASE_URL}/x/y.zip"
        self._patch_urlopen([urllib.error.HTTPError(url, 404, "Not Found", {}, None)])
        result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertIn("HTTP 404", result.reason)
        self.assertEqual(self._bin_contents(), {})

    def test_download_timeout(self):
        self._patch_urlopen(TimeoutError("timed out"))
        result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertIn("timed out", result.reason)
        self.assertEqual(self._bin_contents(), {})

    def test_corrupt_archive(self):
        garbage = b"\x00\x01\x02not an archive\xff" * 100
        self._patch_urlopen([FakeResponse(garbage)])
        result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertIn("corrupt", result.reason)
        self.assertEqual(self._bin_contents(), {})

    def test_missing_sslocal_in_archive(self):
        archive = _archive_bytes({"ssserver": _sslocal_bytes()})
        self._patch_urlopen([FakeResponse(archive)])
        result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertIn("sslocal binary not found", result.reason)
        self.assertEqual(self._bin_contents(), {})

    def test_invalid_executable_format(self):
        bogus = b"ZZZZ" + b"\x00" * (ss_backend.MIN_PLAUSIBLE_SIZE + 1 - 4)
        archive = _archive_bytes({_sslocal_member_name(): bogus})
        self._patch_urlopen([FakeResponse(archive)])
        result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertIn("validation", result.reason)
        self.assertFalse(self.managed.exists())
        self.assertEqual(self._bin_contents(), {})

    def test_failed_version_check(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        self._patch_urlopen([FakeResponse(archive)])
        self._patch_run(returncode=1)
        result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertIn("--version", result.reason)
        self.assertFalse(self.managed.exists())

    def test_existing_backend_untouched_after_failure(self):
        self.bin_dir.mkdir(parents=True)
        self.managed.write_bytes(b"OLD WORKING BACKEND")
        garbage = b"\x00\x01\x02not an archive\xff" * 100
        self._patch_urlopen([FakeResponse(garbage)])
        result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertEqual(self.managed.read_bytes(), b"OLD WORKING BACKEND")
        self.assertEqual(self._bin_contents(),
                         {self.managed.name: b"OLD WORKING BACKEND"})

    def test_temp_files_cleaned_on_failure(self):
        self._patch_urlopen(urllib.error.URLError("boom"))
        ss_backend.install_sslocal()
        self.assertEqual(self._bin_contents(), {})

    def test_invalid_version_rejected(self):
        self._patch_urlopen([])
        result = ss_backend.install_sslocal("../../etc/passwd")
        self.assertFalse(result.ok)
        self.assertIn("Invalid backend version", result.reason)
        self.assertEqual(self._bin_contents(), {})

    def test_unsupported_platform(self):
        with mock.patch.object(ss_backend, "detect_target",
                               side_effect=ValueError("Unsupported platform")):
            result = ss_backend.install_sslocal()
        self.assertFalse(result.ok)
        self.assertIn("Unsupported platform", result.reason)


class EnsureTest(InstallTestCase):

    def test_reuses_existing_usable_backend(self):
        fake = Path("C:/existing/sslocal.exe")
        with mock.patch.object(ss_backend, "find_sslocal",
                               return_value=fake), \
             mock.patch.object(ss_backend, "is_usable",
                               return_value=ss_backend.CheckResult(True, "")):
            urlopen = mock.Mock()
            p = mock.patch.object(ss_backend.urllib.request, "urlopen", urlopen)
            p.start()
            self.addCleanup(p.stop)
            result = ss_backend.ensure_sslocal()
        self.assertTrue(result.ok)
        self.assertEqual(result.path, fake)
        self.assertIn("Reusing", result.reason)
        urlopen.assert_not_called()
        self.assertEqual(self._bin_contents(), {})

    def test_installs_when_existing_unusable(self):
        fake = Path("C:/broken/sslocal.exe")
        real_is_usable = ss_backend.is_usable
        with mock.patch.object(ss_backend, "find_sslocal",
                               return_value=fake), \
             mock.patch.object(
                 ss_backend, "is_usable",
                 side_effect=lambda p: (ss_backend.CheckResult(False, "bad")
                                        if p == fake else real_is_usable(p))):
            self._patch_urlopen(self._success_responses())
            self._patch_run(returncode=0)
            result = ss_backend.ensure_sslocal()
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.path, self.managed)
        self.assertTrue(self.managed.is_file())

    def test_installs_when_nothing_exists(self):
        with mock.patch.object(ss_backend, "find_sslocal", return_value=None):
            self._patch_urlopen(self._success_responses())
            self._patch_run(returncode=0)
            result = ss_backend.ensure_sslocal()
        self.assertTrue(result.ok)
        self.assertEqual(result.path, self.managed)


class ParallelDownloadTest(InstallTestCase):

    def setUp(self):
        orig_probe = ss_backend._probe_range_support
        super().setUp()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        ss_backend._probe_range_support = orig_probe
        self.addCleanup(setattr, ss_backend, "_probe_range_support",
                        orig_probe)

    def _range_response(self, data, content_range=None):
        """Create a FakeResponse that behaves like a Range response."""
        resp = FakeResponse(data)
        resp.status = 206
        resp.headers = {"Content-Range": content_range} if content_range else {}
        return resp

    def _normal_response(self, data):
        """Create a FakeResponse that behaves like a normal (200) response."""
        resp = FakeResponse(data)
        resp.status = 200
        resp.headers = {}
        return resp

    def test_probe_returns_total_size_on_206(self):
        resp = self._range_response(b"\x00", "bytes 0-0/12345")
        p = mock.patch.object(ss_backend, "_open_url",
                              return_value=mock.MagicMock(__enter__=mock.MagicMock(return_value=resp),
                                                          __exit__=mock.MagicMock(return_value=False)))
        p.start()
        self.addCleanup(p.stop)
        self.assertEqual(ss_backend._probe_range_support("http://x"), 12345)

    def test_probe_returns_none_on_200(self):
        resp = self._normal_response(b"\x00")
        p = mock.patch.object(ss_backend, "_open_url",
                              return_value=mock.MagicMock(__enter__=mock.MagicMock(return_value=resp),
                                                          __exit__=mock.MagicMock(return_value=False)))
        p.start()
        self.addCleanup(p.stop)
        self.assertIsNone(ss_backend._probe_range_support("http://x"))

    def test_probe_returns_none_on_error(self):
        p = mock.patch.object(ss_backend, "_open_url",
                              side_effect=urllib.error.URLError("nope"))
        p.start()
        self.addCleanup(p.stop)
        self.assertIsNone(ss_backend._probe_range_support("http://x"))

    def test_probe_returns_none_on_missing_content_range(self):
        resp = self._range_response(b"\x00", "bytes 0-0")
        p = mock.patch.object(ss_backend, "_open_url",
                              return_value=mock.MagicMock(__enter__=mock.MagicMock(return_value=resp),
                                                          __exit__=mock.MagicMock(return_value=False)))
        p.start()
        self.addCleanup(p.stop)
        self.assertIsNone(ss_backend._probe_range_support("http://x"))

    def test_range_calculation_split(self):
        total = 1000
        chunk_size = total // 4
        ranges = []
        for i in range(4):
            start = i * chunk_size
            end = (start + chunk_size - 1) if i < 3 else (total - 1)
            ranges.append((start, end))
        self.assertEqual(ranges, [(0, 249), (250, 499), (500, 749), (750, 999)])
        total_covered = sum(end - start + 1 for start, end in ranges)
        self.assertEqual(total_covered, total)

    def test_range_calculation_non_divisible(self):
        total = 1001
        chunk_size = total // 4
        ranges = []
        for i in range(4):
            start = i * chunk_size
            end = (start + chunk_size - 1) if i < 3 else (total - 1)
            ranges.append((start, end))
        total_covered = sum(end - start + 1 for start, end in ranges)
        self.assertEqual(total_covered, total)

    def test_worker_receives_correct_range_header(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        seen_requests = []

        def capture_open(url, extra_headers=None):
            if extra_headers and "Range" in extra_headers:
                seen_requests.append(extra_headers["Range"])
            return FakeResponse(archive)

        p = mock.patch.object(ss_backend, "_open_url", side_effect=capture_open)
        p.start()
        self.addCleanup(p.stop)

        ss_backend._download_archive_parallel(
            "http://x/archive.tar.xz", self.config_dir / "test.part",
            total_size=len(archive))

        self.assertEqual(len(seen_requests), 4)
        self.assertIn("bytes=0-", seen_requests[0])
        self.assertIn("bytes=", seen_requests[1])

    def test_chunks_reconstructed_in_order(self):
        chunk_data = [b"AAAA", b"BBBB", b"CCCC", b"DDDD"]
        total = sum(len(c) for c in chunk_data)

        call_count = [0]

        def fake_download_range(url, start, end, part_path, lock, state, progress_cb=None):
            chunk_size = len(chunk_data[0])
            idx = min(len(chunk_data) - 1, start // chunk_size)
            part_path.write_bytes(chunk_data[idx])

        p = mock.patch.object(ss_backend, "_download_range_worker",
                              side_effect=fake_download_range)
        p.start()
        self.addCleanup(p.stop)

        dest = self.config_dir / "combined.bin"
        ss_backend._download_archive_parallel("http://x", dest, total)

        self.assertEqual(dest.read_bytes(), b"AAAABBBBCCCCDDDD")

    def test_aggregate_progress_reporting(self):
        chunk_data = [b"A" * 100, b"B" * 100, b"C" * 100, b"D" * 100]
        total = 400
        progress_calls = []

        def fake_download_range(url, start, end, part_path, lock, state, progress_cb=None):
            chunk_size = len(chunk_data[0])
            idx = min(len(chunk_data) - 1, start // chunk_size)
            part_path.write_bytes(chunk_data[idx])
            if progress_cb:
                with lock:
                    state["downloaded"] += len(chunk_data[idx])
                    progress_cb(state["downloaded"], state["total"])

        p = mock.patch.object(ss_backend, "_download_range_worker",
                              side_effect=fake_download_range)
        p.start()
        self.addCleanup(p.stop)

        dest = self.config_dir / "combined.bin"
        ss_backend._download_archive_parallel(
            "http://x", dest, total,
            progress_cb=lambda d, t: progress_calls.append((d, t)))

        self.assertTrue(len(progress_calls) > 0)
        self.assertEqual(progress_calls[-1], (400, 400))

    def test_worker_failure_raises(self):
        def failing_worker(url, start, end, part_path, lock, state, progress_cb=None):
            raise urllib.error.URLError("worker failed")

        p = mock.patch.object(ss_backend, "_download_range_worker",
                              side_effect=failing_worker)
        p.start()
        self.addCleanup(p.stop)

        dest = self.config_dir / "test.bin"
        with self.assertRaises(urllib.error.URLError):
            ss_backend._download_archive_parallel("http://x", dest, 1000)

    def test_partial_files_cleaned_on_failure(self):
        def failing_worker(url, start, end, part_path, lock, state, progress_cb=None):
            part_path.write_bytes(b"data")
            raise RuntimeError("boom")

        p = mock.patch.object(ss_backend, "_download_range_worker",
                              side_effect=failing_worker)
        p.start()
        self.addCleanup(p.stop)

        dest = self.config_dir / "test.bin"
        try:
            ss_backend._download_archive_parallel("http://x", dest, 1000)
        except RuntimeError:
            pass

        part_files = list(self.config_dir.glob(".sslocal-part*.tmp"))
        self.assertEqual(part_files, [])

    def test_fallback_to_single_stream_when_probe_returns_none(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        probe = mock.patch.object(ss_backend, "_probe_range_support",
                                  return_value=None)
        urlopen = mock.patch.object(ss_backend.urllib.request, "urlopen",
                                    return_value=FakeResponse(archive))
        probe.start()
        urlopen.start()
        self.addCleanup(probe.stop)
        self.addCleanup(urlopen.stop)

        dest = self.config_dir / "test.bin"
        ss_backend._download_archive("http://x", dest)
        self.assertEqual(dest.read_bytes(), archive)

    def test_fallback_when_parallel_fails(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        probe = mock.patch.object(ss_backend, "_probe_range_support",
                                  return_value=12345)
        parallel = mock.patch.object(ss_backend, "_download_archive_parallel",
                                     side_effect=urllib.error.URLError("fail"))
        urlopen = mock.patch.object(ss_backend.urllib.request, "urlopen",
                                    return_value=FakeResponse(archive))
        probe.start()
        parallel.start()
        urlopen.start()
        self.addCleanup(probe.stop)
        self.addCleanup(parallel.stop)
        self.addCleanup(urlopen.stop)

        dest = self.config_dir / "test.bin"
        ss_backend._download_archive("http://x", dest)
        self.assertEqual(dest.read_bytes(), archive)

    def test_parallel_download_used_when_probe_succeeds(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        parallel_called = [False]

        def fake_parallel(url, dest, total_size, progress_cb=None):
            parallel_called[0] = True
            dest.write_bytes(archive)

        probe = mock.patch.object(ss_backend, "_probe_range_support",
                                  return_value=len(archive))
        parallel = mock.patch.object(ss_backend, "_download_archive_parallel",
                                     side_effect=fake_parallel)
        probe.start()
        parallel.start()
        self.addCleanup(probe.stop)
        self.addCleanup(parallel.stop)

        dest = self.config_dir / "test.bin"
        ss_backend._download_archive("http://x", dest)
        self.assertTrue(parallel_called[0])
        self.assertEqual(dest.read_bytes(), archive)

    def test_install_sslocal_uses_parallel_download(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        parallel_called = [False]

        def fake_parallel(url, dest, total_size, progress_cb=None):
            parallel_called[0] = True
            dest.write_bytes(archive)

        probe = mock.patch.object(ss_backend, "_probe_range_support",
                                  return_value=len(archive))
        parallel = mock.patch.object(ss_backend, "_download_archive_parallel",
                                     side_effect=fake_parallel)
        self._patch_run(returncode=0)
        probe.start()
        parallel.start()
        self.addCleanup(probe.stop)
        self.addCleanup(parallel.stop)

        result = ss_backend.install_sslocal()
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(parallel_called[0])

    def test_install_sslocal_falls_back_on_parallel_failure(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})

        def fake_parallel(url, dest, total_size, progress_cb=None):
            raise urllib.error.URLError("parallel failed")

        probe = mock.patch.object(ss_backend, "_probe_range_support",
                                  return_value=len(archive))
        parallel = mock.patch.object(ss_backend, "_download_archive_parallel",
                                     side_effect=fake_parallel)
        urlopen = mock.patch.object(ss_backend.urllib.request, "urlopen",
                                    return_value=FakeResponse(archive))
        probe.start()
        parallel.start()
        urlopen.start()
        self.addCleanup(probe.stop)
        self.addCleanup(parallel.stop)
        self.addCleanup(urlopen.stop)
        self._patch_run(returncode=0)

        result = ss_backend.install_sslocal()
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.path, self.managed)


if __name__ == "__main__":
    unittest.main()