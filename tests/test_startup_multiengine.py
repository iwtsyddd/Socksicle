"""Tests for updated utils.startup_utils (multi-engine provisioning)."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from utils.engines.base import EngineType, CheckResult, InstallResult
from utils.engines.sslocal_engine import SslocalEngine
from utils.engines.xray_engine import XrayEngine
from utils.engines.singbox_engine import SingBoxEngine
from utils import startup_utils


@pytest.fixture(autouse=True)
def _qapp_available(qapp):
    return qapp


class ProvisionBackendTest(unittest.TestCase):
    """Test provision_backend with multi-engine support."""

    def setUp(self):
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

    def test_existing_engine_reused(self):
        fake_path = Path("C:/existing/xray")
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = fake_path
        engine_inst.check_usable.return_value = CheckResult(True, "")
        engine_inst.engine_type = EngineType.XRAY
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst):
            result = startup_utils.provision_backend(EngineType.XRAY)
            self.assertTrue(result.ok)
            self.assertEqual(result.path, fake_path)

    def test_missing_engine_triggers_provisioning(self):
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = EngineType.SSLOCAL
        install_result = InstallResult(True, Path("/new/sslocal"), "")
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=install_result):
            result = startup_utils.provision_backend(EngineType.SSLOCAL)
            self.assertTrue(result.ok)

    def test_engine_type_from_settings(self):
        self._mock_mgr.settings = {"engine": "xray"}
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = EngineType.XRAY
        install_result = InstallResult(True, Path("/new/xray"), "")
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst) as get_eng, \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=install_result):
            result = startup_utils.provision_backend()
            # get_engine is called twice: once to check binary, once by ensure_engine
            get_eng.assert_called()

    def test_user_declined(self):
        self._mock_mgr.is_sslocal_declined.return_value = False
        with mock.patch("utils.startup_utils.ask_download_sslocal",
                        return_value=False):
            result = startup_utils.provision_backend(EngineType.SSLOCAL)
            self.assertIsNone(result)
            self._mock_mgr.set_sslocal_declined.assert_called_once_with(True)

    def test_previously_declined_sslocal_does_not_block_xray(self):
        self._mock_mgr.is_sslocal_declined.return_value = True
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = EngineType.XRAY
        install_result = InstallResult(True, Path("/new/xray"), "")
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=install_result):
            result = startup_utils.provision_backend(EngineType.XRAY)
            self.assertTrue(result.ok)

    def test_previously_declined_sslocal_blocks_sslocal(self):
        self._mock_mgr.is_sslocal_declined.return_value = True
        ask = mock.patch("utils.startup_utils.ask_download_sslocal")
        mock_ask = ask.start()
        self.addCleanup(ask.stop)
        result = startup_utils.provision_backend(EngineType.SSLOCAL)
        self.assertIsNone(result)
        mock_ask.assert_not_called()


class ProvisionWorkerTest(unittest.TestCase):
    """Test _ProvisionWorker."""

    def test_worker_calls_ensure_engine(self):
        install_result = InstallResult(True, Path("/new/xray"), "")
        with mock.patch("utils.startup_utils.ensure_engine",
                        return_value=install_result) as ensure:
            worker = startup_utils._ProvisionWorker(EngineType.XRAY)
            results = []
            worker.finished.connect(lambda r: results.append(r))
            worker.run()
            ensure.assert_called_once()
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].ok)

    def test_worker_catches_exceptions(self):
        with mock.patch("utils.startup_utils.ensure_engine",
                        side_effect=RuntimeError("boom")):
            worker = startup_utils._ProvisionWorker(EngineType.SSLOCAL)
            results = []
            worker.finished.connect(lambda r: results.append(r))
            worker.run()
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].ok)
            self.assertIn("Unexpected", results[0].reason)


class AllEnginesProvisioningTest(unittest.TestCase):
    """Test that provisioning works for each engine type."""

    def setUp(self):
        mgr_p = mock.patch("utils.server_manager.ServerManager")
        self._mock_mgr_cls = mgr_p.start()
        self.addCleanup(mgr_p.stop)
        self._mock_mgr = self._mock_mgr_cls.return_value
        self._mock_mgr.is_sslocal_declined.return_value = False
        self._mock_mgr.settings = {}
        ask_p = mock.patch("utils.startup_utils.ask_download_sslocal",
                           return_value=True)
        ask_p.start()
        self.addCleanup(ask_p.stop)

    def _setup_engine(self, engine_type, install_path):
        engine_inst = mock.MagicMock()
        engine_inst.find_binary.return_value = None
        engine_inst.check_usable.return_value = CheckResult(False, "bad")
        engine_inst.engine_type = engine_type
        install_result = InstallResult(True, install_path, "")
        return engine_inst, install_result

    def test_sslocal_engine(self):
        engine_inst, install_result = self._setup_engine(
            EngineType.SSLOCAL, Path("/new/sslocal"))
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst) as get_eng, \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=install_result):
            result = startup_utils.provision_backend(EngineType.SSLOCAL)
            self.assertTrue(result.ok)

    def test_xray_engine(self):
        engine_inst, install_result = self._setup_engine(
            EngineType.XRAY, Path("/new/xray"))
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=install_result):
            result = startup_utils.provision_backend(EngineType.XRAY)
            self.assertTrue(result.ok)

    def test_singbox_engine(self):
        engine_inst, install_result = self._setup_engine(
            EngineType.SINGBOX, Path("/new/sing-box"))
        with mock.patch("utils.startup_utils.get_engine",
                        return_value=engine_inst), \
             mock.patch("utils.startup_utils.ensure_engine",
                        return_value=install_result):
            result = startup_utils.provision_backend(EngineType.SINGBOX)
            self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
