"""Tests for utils.engines (base, sslocal_engine, xray_engine, singbox_engine).

All subprocess and network activity is mocked.
"""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from utils.engines.base import ProxyEngine, EngineType, CheckResult, InstallResult
from utils.engines import common
from utils.engines.sslocal_engine import SslocalEngine
from utils.engines.xray_engine import XrayEngine, _detect_target as xray_detect
from utils.engines.singbox_engine import SingBoxEngine, _detect_target as sb_detect


@pytest.fixture(autouse=True)
def _qapp_available(qapp):
    return qapp


def _magic_for_this_platform():
    if sys.platform == "win32":
        return b"MZ"
    if sys.platform == "darwin":
        return b"\xfe\xed\xfa\xcf"
    return b"\x7fELF"


def _make_file(path, magic=None, size=2_000_000, executable=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    magic = magic if magic is not None else _magic_for_this_platform()
    payload = magic + b"\x00" * (size - len(magic))
    path.write_bytes(payload)
    if executable and os.name != "nt":
        path.chmod(0o755)
    return path


class EngineTypeTest(unittest.TestCase):

    def test_values(self):
        self.assertEqual(EngineType.SSLOCAL.value, "sslocal")
        self.assertEqual(EngineType.XRAY.value, "xray")
        self.assertEqual(EngineType.SINGBOX.value, "sing-box")

    def test_string_enum(self):
        self.assertEqual(str(EngineType.SSLOCAL), "EngineType.SSLOCAL")
        self.assertIsInstance(EngineType.SSLOCAL, str)


class ProxyEngineBaseTest(unittest.TestCase):
    """Test ProxyEngine base class behaviour (via SslocalEngine)."""

    def test_signals_defined(self):
        engine = SslocalEngine()
        self.assertTrue(hasattr(engine, 'statusChanged'))
        self.assertTrue(hasattr(engine, 'connectionStateChanged'))
        self.assertTrue(hasattr(engine, 'logUpdated'))

    def test_default_state(self):
        engine = SslocalEngine()
        self.assertIsNone(engine.process)
        self.assertEqual(engine.local_port, 1080)
        self.assertFalse(engine.is_connected)
        self.assertIsNone(engine.current_server)
        self.assertIsNone(engine.last_exit_code)

    def test_is_running_false_when_no_process(self):
        engine = SslocalEngine()
        self.assertFalse(engine.is_running())

    def test_confirm_connected(self):
        engine = SslocalEngine()
        signals = []
        engine.connectionStateChanged.connect(lambda v: signals.append(v))
        engine.confirm_connected()
        self.assertTrue(engine.is_connected)
        self.assertEqual(signals, [True])

    def test_disconnect_resets_state(self):
        engine = SslocalEngine()
        engine.is_connected = True
        signals = []
        engine.connectionStateChanged.connect(lambda v: signals.append(v))
        engine.disconnect_from_server()
        self.assertFalse(engine.is_connected)
        self.assertIn(False, signals)

    def test_get_current_server(self):
        engine = SslocalEngine()
        self.assertIsNone(engine.get_current_server())
        engine.current_server = "fake"
        self.assertEqual(engine.get_current_server(), "fake")

    def test_teardown_stops_process(self):
        engine = SslocalEngine()
        fake_proc = SimpleNamespace(
            pid=123, poll=mock.Mock(return_value=None),
            terminate=mock.Mock(), wait=mock.Mock(return_value=0))
        engine.process = fake_proc
        engine.is_connected = True
        engine.teardown()
        self.assertIsNone(engine.process)
        self.assertFalse(engine.is_connected)
        fake_proc.terminate.assert_called_once()

    def test_teardown_kills_on_timeout(self):
        engine = SslocalEngine()
        import subprocess
        fake_proc = SimpleNamespace(
            pid=123, poll=mock.Mock(return_value=None),
            terminate=mock.Mock(), kill=mock.Mock(),
            wait=mock.Mock(side_effect=[subprocess.TimeoutExpired("", 2), 0]))
        engine.process = fake_proc
        engine.teardown()
        fake_proc.terminate.assert_called_once()
        fake_proc.kill.assert_called_once()


class SslocalEngineTest(unittest.TestCase):

    def test_engine_type(self):
        self.assertEqual(SslocalEngine.engine_type, EngineType.SSLOCAL)

    def test_process_name(self):
        engine = SslocalEngine()
        self.assertEqual(engine.process_name(), "sslocal")

    def test_version_args(self):
        engine = SslocalEngine()
        self.assertEqual(engine.version_args(), ["--version"])

    def test_build_args_creates_config_file(self):
        engine = SslocalEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        args = engine.build_args(server)
        self.assertEqual(args[0], "-c")
        config_path = Path(args[1])
        self.assertTrue(config_path.exists())
        self.assertTrue(config_path.suffix == ".json")
        import json
        with open(config_path) as f:
            config = json.load(f)
        self.assertEqual(config["server"], "1.2.3.4")
        self.assertEqual(config["server_port"], 8388)
        self.assertEqual(config["method"], "aes-256-gcm")
        self.assertEqual(config["password"], "secret")
        self.assertEqual(config["local_address"], "127.0.0.1")
        self.assertEqual(config["local_port"], 1080)
        config_path.unlink(missing_ok=True)

    def test_build_args_custom_port(self):
        engine = SslocalEngine()
        engine.local_port = 2080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="chacha20-ietf-poly1305", password="pw")
        args = engine.build_args(server)
        config_path = Path(args[1])
        with open(config_path) as f:
            config = __import__("json").load(f)
        self.assertEqual(config["local_port"], 2080)
        config_path.unlink(missing_ok=True)

    def test_build_config_structure(self):
        engine = SslocalEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="5.6.7.8", port=443,
                                  method="chacha20-ietf-poly1305", password="pw123")
        config = engine.build_config(server)
        self.assertEqual(config["server"], "5.6.7.8")
        self.assertEqual(config["server_port"], 443)
        self.assertEqual(config["method"], "chacha20-ietf-poly1305")
        self.assertEqual(config["password"], "pw123")
        self.assertEqual(config["local_address"], "127.0.0.1")
        self.assertEqual(config["local_port"], 1080)

    def test_config_local_port_from_settings_2080(self):
        engine = SslocalEngine()
        engine.local_port = 2080
        server = SimpleNamespace(host="5.6.7.8", port=443,
                                 method="chacha20-ietf-poly1305", password="pw123")
        config = engine.build_config(server)
        self.assertEqual(config["local_port"], 2080)
        self.assertEqual(config["local_address"], "127.0.0.1")
        self.assertEqual(sorted(config.keys()),
                         sorted(["server", "server_port", "method",
                                 "password", "local_address", "local_port"]))

    def test_sslocal_teardown_cleans_config(self):
        engine = SslocalEngine()
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        engine._config_path = Path(path)
        self.assertTrue(Path(path).exists())
        engine.teardown()
        self.assertFalse(Path(path).exists())


class XrayEngineTest(unittest.TestCase):

    def test_engine_type(self):        self.assertEqual(XrayEngine.engine_type, EngineType.XRAY)

    def test_process_name(self):
        engine = XrayEngine()
        self.assertEqual(engine.process_name(), "xray")

    def test_version_args(self):
        engine = XrayEngine()
        self.assertEqual(engine.version_args(), ["version"])

    def test_build_args_creates_config_file(self):
        engine = XrayEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        args = engine.build_args(server)
        self.assertEqual(args[0], "run")
        self.assertEqual(args[1], "-c")
        config_path = Path(args[2])
        self.assertTrue(config_path.exists())
        self.assertTrue(config_path.suffix == ".json")
        import json
        with open(config_path) as f:
            config = json.load(f)
        self.assertIn("inbounds", config)
        self.assertIn("outbounds", config)
        self.assertEqual(config["outbounds"][0]["protocol"], "shadowsocks")
        config_path.unlink(missing_ok=True)

    def test_build_config_structure(self):
        engine = XrayEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        config = engine.build_config(server)
        self.assertIn("log", config)
        self.assertIn("inbounds", config)
        self.assertIn("outbounds", config)
        self.assertIn("routing", config)
        self.assertNotIn("stats", config)
        self.assertNotIn("api", config)
        self.assertEqual(len(config["inbounds"]), 1)
        self.assertEqual(config["inbounds"][0]["protocol"], "socks")
        self.assertEqual(config["inbounds"][0]["tag"], "socks-in")
        self.assertEqual(config["inbounds"][0]["port"], engine.local_port)
        self.assertEqual(config["outbounds"][0]["protocol"], "shadowsocks")

    def test_build_config_server_params(self):
        engine = XrayEngine()
        engine.local_port = 2080
        server = SimpleNamespace(host="5.6.7.8", port=443,
                                 method="chacha20-ietf-poly1305", password="pw123")
        config = engine.build_config(server)
        outbound = config["outbounds"][0]
        srv = outbound["settings"]["servers"][0]
        self.assertEqual(srv["address"], "5.6.7.8")
        self.assertEqual(srv["port"], 443)
        self.assertEqual(srv["method"], "chacha20-ietf-poly1305")
        self.assertEqual(srv["password"], "pw123")

    def test_teardown_cleans_config(self):
        engine = XrayEngine()
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        engine._config_path = Path(path)
        self.assertTrue(Path(path).exists())
        engine.teardown()
        self.assertFalse(Path(path).exists())

    def test_detect_target_win32(self):
        # _detect_target reads platform.machine() and sys.platform directly
        # Just verify it returns a valid target on the current platform
        result = xray_detect()
        valid_targets = ["windows-64", "windows-arm64-v8a",
                         "linux-64", "linux-arm64",
                         "darwin-amd64", "darwin-arm64"]
        self.assertIn(result, valid_targets)


class SingBoxEngineTest(unittest.TestCase):

    def test_engine_type(self):        self.assertEqual(SingBoxEngine.engine_type, EngineType.SINGBOX)

    def test_process_name(self):
        engine = SingBoxEngine()
        self.assertEqual(engine.process_name(), "sing-box")

    def test_version_args(self):
        engine = SingBoxEngine()
        self.assertEqual(engine.version_args(), ["version"])

    def test_build_args_creates_config_file(self):
        engine = SingBoxEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        args = engine.build_args(server)
        self.assertEqual(args[0], "run")
        self.assertEqual(args[1], "-c")
        config_path = Path(args[2])
        self.assertTrue(config_path.exists())
        self.assertTrue(config_path.suffix == ".json")
        import json
        with open(config_path) as f:
            config = json.load(f)
        self.assertIn("inbounds", config)
        self.assertIn("outbounds", config)
        self.assertEqual(config["inbounds"][0]["type"], "mixed")
        self.assertEqual(config["outbounds"][0]["type"], "shadowsocks")
        config_path.unlink(missing_ok=True)

    def test_build_config_structure(self):
        engine = SingBoxEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        config = engine.build_config(server)
        self.assertIn("log", config)
        self.assertIn("inbounds", config)
        self.assertIn("outbounds", config)
        self.assertIn("route", config)
        self.assertEqual(len(config["inbounds"]), 1)
        self.assertEqual(config["inbounds"][0]["type"], "mixed")
        self.assertEqual(config["outbounds"][0]["type"], "shadowsocks")

    def test_build_config_server_params(self):
        engine = SingBoxEngine()
        engine.local_port = 2080
        server = SimpleNamespace(host="5.6.7.8", port=443,
                                 method="chacha20-ietf-poly1305", password="pw123")
        config = engine.build_config(server)
        outbound = config["outbounds"][0]
        self.assertEqual(outbound["server"], "5.6.7.8")
        self.assertEqual(outbound["server_port"], 443)
        self.assertEqual(outbound["method"], "chacha20-ietf-poly1305")
        self.assertEqual(outbound["password"], "pw123")

    def test_no_clash_api_in_config(self):
        engine = SingBoxEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        config = engine.build_config(server)
        self.assertNotIn("experimental", config)
        self.assertEqual(len(config["inbounds"]), 1)
        self.assertEqual(config["inbounds"][0]["listen_port"], 1080)

    def test_route_final_is_proxy(self):
        engine = SingBoxEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        config = engine.build_config(server)
        self.assertEqual(config["route"]["final"], "proxy")

    def test_singbox_teardown_cleans_config(self):
        engine = SingBoxEngine()
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        engine._config_path = Path(path)
        self.assertTrue(Path(path).exists())
        engine.teardown()
        self.assertFalse(Path(path).exists())


class SslocalEngineBinaryTest(unittest.TestCase):
    """Test sslocal_engine binary finding and usability."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_find_binary_returns_none_when_missing(self):
        engine = SslocalEngine()
        with mock.patch("utils.ss_backend.get_app_dir", return_value=self.root / "app"), \
             mock.patch("utils.ss_backend.get_config_dir", return_value=self.root / "config"), \
             mock.patch("utils.ss_backend.shutil.which", return_value=None):
            result = engine.find_binary()
            self.assertIsNone(result)

    def test_check_usable_none(self):
        engine = SslocalEngine()
        result = engine.check_usable(None)
        self.assertFalse(result.usable)
        self.assertIn("No sslocal path", result.reason)


class XrayEngineBinaryTest(unittest.TestCase):
    """Test xray_engine binary finding and usability."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_check_usable_none(self):
        engine = XrayEngine()
        result = engine.check_usable(None)
        self.assertFalse(result.usable)
        self.assertIn("No xray path", result.reason)

    def test_find_binary_discovers_manual_subdir_app(self):
        fake = _make_file(self.root / "bin" / "xray"
                          / common._binary_name("xray"))
        with mock.patch("utils.platform_utils.get_app_dir",
                        return_value=self.root), \
             mock.patch("utils.platform_utils.get_config_dir",
                        return_value=self.root / "config"), \
             mock.patch.object(common.shutil, "which", return_value=None):
            result = common._find_binary("xray")
        self.assertEqual(result, fake)

    def test_find_binary_discovers_manual_subdir_config(self):
        fake = _make_file(self.root / "config" / "bin" / "xray"
                          / common._binary_name("xray"))
        with mock.patch("utils.platform_utils.get_app_dir",
                        return_value=self.root / "app"), \
             mock.patch("utils.platform_utils.get_config_dir",
                        return_value=self.root / "config"), \
             mock.patch.object(common.shutil, "which", return_value=None):
            result = common._find_binary("xray")
        self.assertEqual(result, fake)

    def test_find_binary_prefers_flat_bin_over_subdir(self):
        expected = _make_file(self.root / "bin"
                              / common._binary_name("xray"))
        _make_file(self.root / "bin" / "xray"
                   / common._binary_name("xray"))
        with mock.patch("utils.platform_utils.get_app_dir",
                        return_value=self.root), \
             mock.patch("utils.platform_utils.get_config_dir",
                        return_value=self.root / "config"), \
             mock.patch.object(common.shutil, "which", return_value=None):
            result = common._find_binary("xray")
        self.assertEqual(result, expected)

    def test_check_usable_too_small(self):
        engine = XrayEngine()
        path = _make_file(self.root / "xray", size=1000)
        result = engine.check_usable(path)
        self.assertFalse(result.usable)
        self.assertIn("too small", result.reason)


class SingBoxEngineBinaryTest(unittest.TestCase):
    """Test singbox_engine binary finding and usability."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_check_usable_none(self):
        engine = SingBoxEngine()
        result = engine.check_usable(None)
        self.assertFalse(result.usable)
        self.assertIn("No sing-box path", result.reason)

    def test_find_binary_discovers_manual_singbox_subdir(self):
        fake = _make_file(self.root / "bin" / "singbox"
                          / common._binary_name("sing-box"))
        with mock.patch("utils.platform_utils.get_app_dir",
                        return_value=self.root), \
             mock.patch("utils.platform_utils.get_config_dir",
                        return_value=self.root / "config"), \
             mock.patch.object(common.shutil, "which", return_value=None):
            result = common._find_binary("sing-box")
        self.assertEqual(result, fake)

    def test_local_bin_subdir_mapping(self):
        self.assertEqual(common._local_bin_subdir("sing-box"), "singbox")
        self.assertEqual(common._local_bin_subdir("xray"), "xray")
        self.assertEqual(common._local_bin_subdir("sslocal"), "sslocal")

    def test_check_usable_too_small(self):
        engine = SingBoxEngine()
        path = _make_file(self.root / "sing-box", size=1000)
        result = engine.check_usable(path)
        self.assertFalse(result.usable)
        self.assertIn("too small", result.reason)


if __name__ == "__main__":
    unittest.main()
