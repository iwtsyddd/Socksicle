"""Tests for utils.engines.engine_manager (registry, selection, provisioning)."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from utils.engines.base import EngineType, CheckResult, InstallResult
from utils.engines.sslocal_engine import SslocalEngine
from utils.engines.xray_engine import XrayEngine
from utils.engines.singbox_engine import SingBoxEngine
from utils.engines import engine_manager as em


@pytest.fixture(autouse=True)
def _qapp_available(qapp):
    return qapp


class RegistrationTest(unittest.TestCase):
    """Test engine registration and lookup."""


    def test_all_engines_registered(self):
        classes = em.get_engine_classes()
        self.assertIn(EngineType.SSLOCAL, classes)
        self.assertIn(EngineType.XRAY, classes)
        self.assertIn(EngineType.SINGBOX, classes)
        self.assertEqual(classes[EngineType.SSLOCAL], SslocalEngine)
        self.assertEqual(classes[EngineType.XRAY], XrayEngine)
        self.assertEqual(classes[EngineType.SINGBOX], SingBoxEngine)

    def test_get_all_engine_types(self):
        types = em.get_all_engine_types()
        self.assertEqual(len(types), 3)
        self.assertEqual(types[0], EngineType.SSLOCAL)
        self.assertEqual(types[1], EngineType.XRAY)
        self.assertEqual(types[2], EngineType.SINGBOX)

    def test_get_engine_returns_singleton(self):
        e1 = em.get_engine(EngineType.SSLOCAL)
        e2 = em.get_engine(EngineType.SSLOCAL)
        self.assertIs(e1, e2)

    def test_get_engine_by_class(self):
        e = em.get_engine(SslocalEngine)
        self.assertIsInstance(e, SslocalEngine)
        self.assertEqual(e.engine_type, EngineType.SSLOCAL)

    def test_get_engine_different_types(self):
        ss = em.get_engine(EngineType.SSLOCAL)
        xr = em.get_engine(EngineType.XRAY)
        sb = em.get_engine(EngineType.SINGBOX)
        self.assertIsNot(ss, xr)
        self.assertIsNot(xr, sb)
        self.assertIsNot(ss, sb)


class GetCurrentEngineTest(unittest.TestCase):
    """Test get_current_engine with settings dict."""


    def test_default_engine_is_sslocal(self):
        engine = em.get_current_engine({})
        self.assertEqual(engine.engine_type, EngineType.SSLOCAL)

    def test_sslocal_setting(self):
        engine = em.get_current_engine({"engine": "sslocal"})
        self.assertEqual(engine.engine_type, EngineType.SSLOCAL)

    def test_xray_setting(self):
        engine = em.get_current_engine({"engine": "xray"})
        self.assertEqual(engine.engine_type, EngineType.XRAY)

    def test_singbox_setting(self):
        engine = em.get_current_engine({"engine": "sing-box"})
        self.assertEqual(engine.engine_type, EngineType.SINGBOX)

    def test_unknown_engine_falls_back_to_sslocal(self):
        engine = em.get_current_engine({"engine": "unknown"})
        self.assertEqual(engine.engine_type, EngineType.SSLOCAL)


class CheckEngineTest(unittest.TestCase):
    """Test check_engine function."""


    def test_check_engine_returns_check_result(self):
        # Mock find_binary to return None (no binary found)
        with mock.patch.object(SslocalEngine, "find_binary", return_value=None):
            result = em.check_engine(EngineType.SSLOCAL)
            self.assertIsInstance(result, CheckResult)
            self.assertFalse(result.usable)
            self.assertIn("not found", result.reason)

    def test_check_engine_with_usable_binary(self):
        fake_path = Path("C:/fake/sslocal")
        with mock.patch.object(SslocalEngine, "find_binary", return_value=fake_path), \
             mock.patch.object(SslocalEngine, "check_usable",
                               return_value=CheckResult(True, "")):
            result = em.check_engine(EngineType.SSLOCAL)
            self.assertTrue(result.usable)


class EnsureEngineTest(unittest.TestCase):
    """Test ensure_engine function."""


    def test_reuses_existing_usable(self):
        fake_path = Path("C:/fake/sslocal")
        with mock.patch.object(SslocalEngine, "find_binary", return_value=fake_path), \
             mock.patch.object(SslocalEngine, "check_usable",
                               return_value=CheckResult(True, "")) as check, \
             mock.patch.object(SslocalEngine, "install") as install:
            result = em.ensure_engine(EngineType.SSLOCAL)
            self.assertTrue(result.ok)
            self.assertEqual(result.path, fake_path)
            self.assertIn("Reusing", result.reason)
            install.assert_not_called()

    def test_installs_when_missing(self):
        install_result = InstallResult(True, Path("/new/sslocal"), "")
        with mock.patch.object(SslocalEngine, "find_binary", return_value=None), \
             mock.patch.object(SslocalEngine, "install",
                               return_value=install_result) as install:
            result = em.ensure_engine(EngineType.SSLOCAL)
            self.assertTrue(result.ok)
            install.assert_called_once()

    def test_installs_when_unusable(self):
        fake_path = Path("C:/fake/sslocal")
        install_result = InstallResult(True, Path("/new/sslocal"), "")
        with mock.patch.object(SslocalEngine, "find_binary", return_value=fake_path), \
             mock.patch.object(SslocalEngine, "check_usable",
                               return_value=CheckResult(False, "bad")), \
             mock.patch.object(SslocalEngine, "install",
                               return_value=install_result) as install:
            result = em.ensure_engine(EngineType.SSLOCAL)
            self.assertTrue(result.ok)
            install.assert_called_once()


class SwitchEngineTest(unittest.TestCase):
    """Test switch_engine function."""


    def test_switch_engine_updates_settings(self):
        settings = {"engine": "sslocal"}
        conn_mgr = mock.MagicMock()
        conn_mgr.is_connected = False
        new_engine = em.switch_engine(settings, EngineType.XRAY, conn_mgr)
        self.assertEqual(settings["engine"], "xray")
        self.assertEqual(new_engine.engine_type, EngineType.XRAY)

    def test_switch_engine_disconnects_if_connected(self):
        settings = {"engine": "sslocal"}
        conn_mgr = mock.MagicMock()
        conn_mgr.is_connected = True
        em.switch_engine(settings, EngineType.XRAY, conn_mgr)
        conn_mgr.disconnect.assert_called_once()

    def test_switch_engine_without_connection_manager(self):
        settings = {"engine": "sslocal"}
        new_engine = em.switch_engine(settings, EngineType.SINGBOX)
        self.assertEqual(settings["engine"], "sing-box")
        self.assertEqual(new_engine.engine_type, EngineType.SINGBOX)


class InstallEngineTest(unittest.TestCase):
    """Test install_engine delegates correctly."""


    def test_install_engine_calls_engine_install(self):
        install_result = InstallResult(True, Path("/new/xray"), "")
        with mock.patch.object(XrayEngine, "install",
                               return_value=install_result) as install:
            result = em.install_engine(EngineType.XRAY)
            self.assertTrue(result.ok)
            install.assert_called_once()


if __name__ == "__main__":
    unittest.main()
