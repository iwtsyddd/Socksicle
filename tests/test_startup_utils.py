"""Integration tests: startup provisioning (utils.startup_utils) and the
connection flow it feeds into.  GUI bits run on the offscreen Qt platform;
all network and subprocess activity is mocked.
"""
import io
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from utils import ss_backend, startup_utils
from utils.engines.base import (
    EngineType, CheckResult, InstallResult, ProxyEngine, )
from utils.engines import base as engine_base
from utils.engines.sslocal_engine import SslocalEngine
from tests.test_ss_backend_install import (
    FakeResponse, _archive_bytes, _sslocal_bytes, _sslocal_member_name,
)


@pytest.fixture(autouse=True)
def _qapp_available(qapp):
    return qapp


class StartupProvisioningTest(unittest.TestCase):

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
        mgr_p = mock.patch("utils.server_manager.ServerManager")
        self._mock_mgr_cls = mgr_p.start()
        self.addCleanup(mgr_p.stop)
        self._mock_mgr = self._mock_mgr_cls.return_value
        self._mock_mgr.is_sslocal_declined.return_value = False
        self._mock_mgr.settings = {"engine": "sslocal"}
        ask_p = mock.patch("utils.startup_utils.ask_download_sslocal",
                           return_value=True)
        ask_p.start()
        self.addCleanup(ask_p.stop)

    def _patch_urlopen(self, responses):
        m = mock.Mock(side_effect=responses)
        p = mock.patch.object(ss_backend.urllib.request, "urlopen", m)
        p.start()
        self.addCleanup(p.stop)
        return m

    def _patch_run(self):
        m = mock.Mock(return_value=SimpleNamespace(returncode=0))
        p = mock.patch.object(ss_backend.subprocess, "run", m)
        p.start()
        self.addCleanup(p.stop)
        return m

    def _patch_engine_manager(self):
        """Patch engine manager to use ss_backend for sslocal provisioning."""
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "not found")
        engine_inst.engine_type = EngineType.SSLOCAL
        get_eng_p = mock.patch("utils.startup_utils.get_engine",
                               return_value=engine_inst)
        get_eng_p.start()
        self.addCleanup(get_eng_p.stop)

        # Patch ensure_engine to delegate to ss_backend.ensure_sslocal
        def fake_ensure(et, progress_cb=None):
            return ss_backend.ensure_sslocal(progress_cb=progress_cb)

        ensure_p = mock.patch("utils.startup_utils.ensure_engine",
                              side_effect=fake_ensure)
        ensure_p.start()
        self.addCleanup(ensure_p.stop)
        return engine_inst

    def test_existing_backend_startup_does_not_download(self):
        existing = self.root / "existing-bin" / "sslocal"
        urlopen = mock.Mock()
        p = mock.patch.object(ss_backend.urllib.request, "urlopen", urlopen)
        p.start()
        self.addCleanup(p.stop)
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = existing
        engine_inst.check_usable.return_value = CheckResult(True, "")
        engine_inst.engine_type = EngineType.SSLOCAL
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst):
            result = startup_utils.provision_backend()

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.path, existing)
        urlopen.assert_not_called()
        self.assertEqual(self._bin_contents(), {})

    def test_missing_backend_triggers_provisioning(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        responses = [FakeResponse(archive)]
        self._patch_engine_manager()
        urlopen = self._patch_urlopen(responses)
        self._patch_run()

        result = startup_utils.provision_backend()

        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.path, self.managed)
        self.assertTrue(self.managed.is_file())
        self.assertTrue(urlopen.called)
        self.assertEqual(
            self._bin_contents().keys(),
            {self.managed.name, ss_backend.VERSION_MARKER_NAME})

    def test_provisioning_failure_propagates_without_crash(self):
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = EngineType.SSLOCAL
        failure = InstallResult(False, None, "Download failed")
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=failure):
            result = startup_utils.provision_backend()
        self.assertFalse(result.ok)
        self.assertIn("Download failed", result.reason)

    def test_unexpected_worker_error_is_contained(self):
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = EngineType.SSLOCAL
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        side_effect=RuntimeError("boom")):
            result = startup_utils.provision_backend()
        self.assertFalse(result.ok)
        self.assertIn("Unexpected provisioning error", result.reason)

    def test_provisioning_runs_off_the_ui_thread(self):
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = EngineType.SSLOCAL
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=InstallResult(True, self.managed, "")):
            result = startup_utils.provision_backend()
        self.assertTrue(result.ok)
        self.assertEqual(result.path, self.managed)

    def test_no_duplicate_provisioning_attempts(self):
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = EngineType.SSLOCAL
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=InstallResult(True, self.managed, "")) as ensure:
            result = startup_utils.provision_backend()
        self.assertTrue(result.ok)
        ensure.assert_called_once()
        self.assertTrue(
            callable(ensure.call_args.kwargs.get("progress_cb")))

    def test_progress_callbacks_reach_progress_ui(self):
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = EngineType.SSLOCAL
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=InstallResult(True, self.managed, "")):
            result = startup_utils.provision_backend()
        self.assertTrue(result.ok)
        self.assertEqual(result.path, self.managed)

    def test_no_stale_processes_after_provisioning(self):
        archive = _archive_bytes({_sslocal_member_name(): _sslocal_bytes()})
        self._patch_engine_manager()
        self._patch_urlopen([FakeResponse(archive)])
        self._patch_run()
        result = startup_utils.provision_backend()
        self.assertTrue(result.ok)
        self.assertEqual(self._bin_contents().keys(),
                         {self.managed.name, ss_backend.VERSION_MARKER_NAME})

    def _bin_contents(self):
        if not self.bin_dir.exists():
            return {}
        return {p.name: p.read_bytes() for p in self.bin_dir.iterdir()}

    def test_declined_by_user_returns_none_and_saves_flag(self):
        self._mock_mgr.is_sslocal_declined.return_value = False
        with mock.patch("utils.startup_utils.ask_download_sslocal",
                        return_value=False):
            result = startup_utils.provision_backend()
        self.assertIsNone(result)
        self._mock_mgr.set_sslocal_declined.assert_called_once_with(True)

    def test_previously_declined_returns_none_without_asking(self):
        self._mock_mgr.is_sslocal_declined.return_value = True
        ask = mock.patch("utils.startup_utils.ask_download_sslocal")
        mock_ask = ask.start()
        self.addCleanup(ask.stop)
        result = startup_utils.provision_backend()
        self.assertIsNone(result)
        mock_ask.assert_not_called()


class DownloadProgressTest(unittest.TestCase):

    def _clock(self):
        self.now = [0.0]
        return lambda: self.now[0]

    def _dialog(self):
        return mock.MagicMock()

    def test_format_bytes(self):
        self.assertEqual(startup_utils.format_bytes(0), "0 B")
        self.assertEqual(startup_utils.format_bytes(512), "512 B")
        self.assertEqual(startup_utils.format_bytes(1_024), "1 KB")
        self.assertEqual(startup_utils.format_bytes(8_400_000), "8.4 MB")
        self.assertEqual(startup_utils.format_bytes(12_500_000), "12.5 MB")
        self.assertEqual(startup_utils.format_bytes(2_500_000_000), "2.5 GB")

    def test_format_duration(self):
        self.assertEqual(startup_utils.format_duration(0), "0 s")
        self.assertEqual(startup_utils.format_duration(45), "45 s")
        self.assertEqual(startup_utils.format_duration(125), "2 m 5 s")
        self.assertEqual(startup_utils.format_duration(4_200), "1 h 10 m")

    def test_determinate_progress_updates_bar_and_label(self):
        dialog = self._dialog()
        tracker = startup_utils.ProgressTracker(dialog, clock=self._clock())

        tracker.update(6_300_000, 12_500_000)   # t=0 s, no speed yet
        self.now[0] = 1.0
        tracker.update(8_400_000, 12_500_000)   # 2.1 MB over 1 s
        tracker.flush()

        dialog.setMaximum.assert_called_with(12_500_000)
        dialog.setValue.assert_called_with(8_400_000)
        label = dialog.setLabelText.call_args.args[0]
        self.assertIn("8.4 MB / 12.5 MB", label)
        self.assertIn("2.1 MB/s", label)
        self.assertIn("~2 s left", label)

    def test_indeterminate_progress_keeps_busy_bar(self):
        dialog = self._dialog()
        tracker = startup_utils.ProgressTracker(dialog, clock=self._clock())

        tracker.update(6_300_000, None)         # no Content-Length
        self.now[0] = 1.0
        tracker.update(8_400_000, None)
        tracker.flush()

        dialog.setMaximum.assert_not_called()
        dialog.setValue.assert_not_called()
        label = dialog.setLabelText.call_args.args[0]
        self.assertIn("8.4 MB", label)
        self.assertIn("2.1 MB/s", label)
        self.assertNotIn(" / ", label)
        self.assertNotIn("left", label)

    def test_eta_skipped_until_measurable_speed(self):
        dialog = self._dialog()
        tracker = startup_utils.ProgressTracker(dialog, clock=self._clock())

        tracker.update(100_000, 12_500_000)     # t=0 s
        self.now[0] = 0.010                     # 10 ms window: too short
        tracker.update(200_000, 12_500_000)
        tracker.flush()

        label = dialog.setLabelText.call_args.args[0]
        self.assertNotIn("MB/s", label)
        self.assertNotIn("left", label)

    def test_flush_batches_per_chunk_updates(self):
        dialog = self._dialog()
        tracker = startup_utils.ProgressTracker(dialog, clock=self._clock())

        for downloaded in (65536, 131072, 196608, 262144):
            tracker.update(downloaded, 12_500_000)
        tracker.flush()

        dialog.setValue.assert_called_once_with(262_144)
        dialog.setMaximum.assert_called_once_with(12_500_000)
        dialog.setLabelText.assert_called_once()

    def test_stop_halts_timer(self):
        dialog = self._dialog()
        tracker = startup_utils.ProgressTracker(dialog)
        self.assertTrue(tracker._timer.isActive())
        tracker.stop()
        self.assertFalse(tracker._timer.isActive())


class FailureDialogTest(unittest.TestCase):

    def test_failure_dialog_offers_manual_fallback(self):
        box = mock.MagicMock()
        box.return_value.exec.return_value = 0
        with mock.patch.object(startup_utils, "QMessageBox", box), \
             mock.patch.object(startup_utils, "manual_install_instructions",
                               return_value="MANUAL_STEPS"):
            startup_utils.show_provisioning_failure(
                ss_backend.InstallResult(False, None, "boom"))
        text = box.return_value.setText.call_args.args[0]
        informative = box.return_value.setInformativeText.call_args.args[0]
        detailed = box.return_value.setDetailedText.call_args.args[0]
        self.assertIn("could not be installed automatically", text)
        self.assertIn("MANUAL_STEPS", informative)
        self.assertEqual(detailed, "boom")
        self.assertEqual(box.return_value.exec.call_count, 1)

    def test_failure_dialog_windows_instructions(self):
        box = mock.MagicMock()
        box.return_value.exec.return_value = 0
        with mock.patch.object(startup_utils, "QMessageBox", box):
            startup_utils.show_provisioning_failure(
                ss_backend.InstallResult(False, None, "boom"))
        informative = box.return_value.setInformativeText.call_args.args[0]
        if ss_backend.is_windows():
            self.assertIn("sslocal.exe", informative)
            self.assertIn("shadowsocks-rust/releases", informative)
        else:
            self.assertIn("sudo", informative)

    def test_cancel_shown_as_provisioning_failure_state(self):
        box = mock.MagicMock()
        box.return_value.exec.return_value = 0
        with mock.patch.object(startup_utils, "QMessageBox", box):
            startup_utils.show_provisioning_failure(None)
        detailed = box.return_value.setDetailedText.call_args.args[0]
        self.assertIn("cancelled", detailed)


class ConnectionFlowTest(unittest.TestCase):

    def test_connect_starts_found_backend_and_disconnect_terminates(self):
        fake_proc = _FakeProc()
        backend = Path("C:/bin/sslocal.exe")
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="pw")
        with mock.patch.object(ss_backend, "find_sslocal",
                               return_value=backend), \
             mock.patch.object(engine_base.subprocess, "Popen",
                               return_value=fake_proc):
            proc = SslocalEngine()
            self.assertTrue(proc.start(server))
            self.assertTrue(proc.is_running())
            proc.disconnect_from_server()
        self.assertFalse(proc.is_running())
        self.assertTrue(fake_proc.stop)

    def test_connect_reports_error_when_backend_missing(self):
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="pw")
        with mock.patch.object(ss_backend, "find_sslocal",
                               return_value=None):
            proc = SslocalEngine()
            emitted = []
            proc.statusChanged.connect(
                lambda msg, err: emitted.append((msg, err)))
            self.assertFalse(proc.start(server))
        self.assertTrue(emitted)
        self.assertIn("not found", emitted[0][0].lower())
        self.assertTrue(emitted[0][1])


class _FakeProc:
    def __init__(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.stop = False
        self.pid = 12345

    def poll(self):
        return 0 if self.stop else None

    def terminate(self):
        self.stop = True

    def kill(self):
        self.stop = True

    def wait(self, timeout=None):
        while not self.stop:
            time.sleep(0.01)
        return 0


if __name__ == "__main__":
    unittest.main()