"""Tests for sing-box config generation for VLESS and VMess protocols."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.server_model import Server, ProxyProtocol
from utils.engines.singbox_engine import (
    SingBoxEngine,
    _generate_config,
    _build_singbox_vless_outbound,
    _build_singbox_vmess_outbound,
    _build_singbox_ss_outbound,
    _build_singbox_transport,
)


@pytest.fixture(autouse=True)
def _qapp_available(qapp):
    return qapp


class _FakeServer:
    """Minimal object mimicking Server fields for engine tests."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class SingBoxVlessConfigTest(unittest.TestCase):

    def test_vless_outbound_basic(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VLESS,
            host="1.2.3.4", port=443,
            uuid="test-uuid", flow="", security="none",
            transport="tcp", server_name="", fingerprint="",
            public_key="", short_id="", path="", host_header="",
        )
        ob = _build_singbox_vless_outbound(server)
        self.assertEqual(ob["type"], "vless")
        self.assertEqual(ob["server"], "1.2.3.4")
        self.assertEqual(ob["server_port"], 443)
        self.assertEqual(ob["uuid"], "test-uuid")
        self.assertNotIn("flow", ob)
        self.assertNotIn("tls", ob)
        self.assertNotIn("transport", ob)

    def test_vless_outbound_reality(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VLESS,
            host="reality.host", port=443,
            uuid="uuid-r", flow="xtls-rprx-vision",
            security="reality",
            transport="tcp", server_name="sni.example.com",
            fingerprint="chrome",
            public_key="PUBKEY123", short_id="SHORT",
            path="", host_header="",
        )
        ob = _build_singbox_vless_outbound(server)
        self.assertEqual(ob["flow"], "xtls-rprx-vision")
        self.assertIn("tls", ob)
        tls = ob["tls"]
        self.assertTrue(tls["enabled"])
        self.assertEqual(tls["server_name"], "sni.example.com")
        self.assertEqual(tls["utls"]["fingerprint"], "chrome")
        self.assertTrue(tls["reality"]["enabled"])
        self.assertEqual(tls["reality"]["public_key"], "PUBKEY123")
        self.assertEqual(tls["reality"]["short_id"], "SHORT")

    def test_vless_outbound_tls_ws(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VLESS,
            host="ws.host", port=8443,
            uuid="uuid-ws", flow="", security="tls",
            transport="ws", server_name="ws.example.com",
            fingerprint="firefox",
            public_key="", short_id="",
            path="/vless-ws", host_header="cdn.example.com",
        )
        ob = _build_singbox_vless_outbound(server)
        self.assertIn("tls", ob)
        self.assertNotIn("reality", ob["tls"])
        self.assertIn("transport", ob)
        tr = ob["transport"]
        self.assertEqual(tr["type"], "ws")
        self.assertEqual(tr["path"], "/vless-ws")
        self.assertEqual(tr["headers"]["Host"], "cdn.example.com")

    def test_vless_outbound_grpc(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VLESS,
            host="grpc.host", port=443,
            uuid="uuid-g", flow="", security="tls",
            transport="grpc", server_name="grpc.server",
            fingerprint="chrome",
            public_key="", short_id="",
            path="my-service", host_header="",
        )
        ob = _build_singbox_vless_outbound(server)
        self.assertIn("transport", ob)
        tr = ob["transport"]
        self.assertEqual(tr["type"], "grpc")
        self.assertEqual(tr["service_name"], "my-service")

    def test_vless_full_config(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VLESS,
            host="1.2.3.4", port=443,
            uuid="uuid-full", flow="xtls-rprx-vision",
            security="reality", transport="tcp",
            server_name="sni.com", fingerprint="chrome",
            public_key="PBK", short_id="SID",
            path="", host_header="",
            method="", password="",
        )
        config = _generate_config(server, 1080)
        self.assertIn("log", config)
        self.assertIn("inbounds", config)
        self.assertIn("outbounds", config)
        self.assertIn("route", config)
        self.assertEqual(config["inbounds"][0]["type"], "mixed")
        self.assertEqual(config["inbounds"][0]["listen_port"], 1080)
        ob = config["outbounds"][0]
        self.assertEqual(ob["type"], "vless")
        self.assertEqual(ob["uuid"], "uuid-full")
        self.assertEqual(config["route"]["final"], "proxy")

    def test_route_rules_no_geoip_cidr(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VLESS,
            host="1.2.3.4", port=443,
            uuid="uuid-route", flow="", security="none",
            transport="tcp", server_name="", fingerprint="",
            public_key="", short_id="", path="", host_header="",
            method="", password="",
        )
        config = _generate_config(server, 1080)
        rules = config["route"]["rules"]
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0], {"protocol": "dns", "outbound": "direct"})
        self.assertEqual(rules[1], {"ip_is_private": True, "outbound": "direct"})
        for rule in rules:
            self.assertNotIn("ip_cidr", rule)
            self.assertNotIn("geoip", json.dumps(rule))


class SingBoxVmessConfigTest(unittest.TestCase):

    def test_vmess_outbound_basic(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VMESS,
            host="vm.host", port=443,
            uuid="vm-uuid", alter_id=0,
            vmess_security="auto", security="tls",
            transport="tcp", server_name="vm.sni",
            fingerprint="chrome",
            path="", host_header="",
        )
        ob = _build_singbox_vmess_outbound(server)
        self.assertEqual(ob["type"], "vmess")
        self.assertEqual(ob["server"], "vm.host")
        self.assertEqual(ob["server_port"], 443)
        self.assertEqual(ob["uuid"], "vm-uuid")
        self.assertEqual(ob["alter_id"], 0)
        self.assertEqual(ob["security"], "auto")
        self.assertIn("tls", ob)
        self.assertNotIn("transport", ob)

    def test_vmess_outbound_no_tls(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VMESS,
            host="vm.host", port=80,
            uuid="vm-uuid2", alter_id=2,
            vmess_security="chacha20-poly1305",
            security="none", transport="ws",
            server_name="", fingerprint="firefox",
            path="/vmess-ws", host_header="vm.host",
        )
        ob = _build_singbox_vmess_outbound(server)
        self.assertNotIn("tls", ob)
        self.assertIn("transport", ob)
        tr = ob["transport"]
        self.assertEqual(tr["type"], "ws")
        self.assertEqual(tr["path"], "/vmess-ws")
        self.assertEqual(tr["headers"]["Host"], "vm.host")

    def test_vmess_outbound_grpc(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VMESS,
            host="g.host", port=443,
            uuid="uuid-grpc", alter_id=0,
            vmess_security="auto", security="tls",
            transport="grpc", server_name="g.sni",
            fingerprint="chrome",
            path="grpc-svc", host_header="",
        )
        ob = _build_singbox_vmess_outbound(server)
        self.assertIn("transport", ob)
        self.assertEqual(ob["transport"]["type"], "grpc")
        self.assertEqual(ob["transport"]["service_name"], "grpc-svc")

    def test_vmess_full_config(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VMESS,
            host="5.6.7.8", port=443,
            uuid="uuid-vm-full", alter_id=0,
            vmess_security="auto", security="tls",
            transport="ws", server_name="sni.example.com",
            fingerprint="chrome",
            path="/path", host_header="host.example.com",
            method="", password="",
        )
        config = _generate_config(server, 1080)
        self.assertEqual(config["outbounds"][0]["type"], "vmess")
        self.assertEqual(config["outbounds"][0]["uuid"], "uuid-vm-full")
        self.assertEqual(config["outbounds"][0]["alter_id"], 0)
        self.assertEqual(config["route"]["final"], "proxy")

    def test_route_rule_uses_ip_is_private(self):
        server = _FakeServer(
            protocol=ProxyProtocol.VMESS,
            host="5.6.7.8", port=443,
            uuid="uuid-vm-route", alter_id=0,
            vmess_security="auto", security="tls",
            transport="ws", server_name="sni.example.com",
            fingerprint="chrome",
            path="/path", host_header="host.example.com",
            method="", password="",
        )
        config = _generate_config(server, 1080)
        rule = config["route"]["rules"][1]
        self.assertIn("ip_is_private", rule)
        self.assertEqual(rule["ip_is_private"], True)
        self.assertNotIn("ip_cidr", rule)


class SingBoxPortsConfigTest(unittest.TestCase):
    """Inbound invariants: one mixed listener on the local port only."""

    def _server(self):
        return _FakeServer(
            protocol=ProxyProtocol.SHADOWSOCKS,
            host="1.2.3.4", port=8388,
            method="aes-256-gcm", password="secret",
        )

    def test_single_inbound_mixed(self):
        config = _generate_config(self._server(), 1080)
        self.assertEqual(len(config["inbounds"]), 1)
        inbound = config["inbounds"][0]
        self.assertEqual(inbound["type"], "mixed")
        self.assertEqual(inbound["tag"], "mixed-in")
        self.assertEqual(inbound["listen"], "127.0.0.1")

    def test_inbound_listen_port_equals_local_port(self):
        config = _generate_config(self._server(), 2080)
        self.assertEqual(config["inbounds"][0]["listen_port"], 2080)

    def test_no_clash_api_section(self):
        config = _generate_config(self._server(), 1080)
        self.assertNotIn("experimental", config)

    def test_no_duplicate_listen_ports(self):
        config = _generate_config(self._server(), 1080)
        text = json.dumps(config)
        self.assertEqual(len(config["inbounds"]), 1)
        self.assertEqual(text.count('"listen_port"'), 1)
        self.assertEqual(text.count("127.0.0.1:"), 0)

    def test_local_port_9090_no_conflict(self):
        config = _generate_config(self._server(), 9090)
        self.assertEqual(config["inbounds"][0]["listen_port"], 9090)
        self.assertNotIn("experimental", config)

    def test_engine_build_config_no_clash(self):
        engine = SingBoxEngine()
        engine.local_port = 2080
        config = engine.build_config(self._server())
        self.assertEqual(len(config["inbounds"]), 1)
        self.assertEqual(config["inbounds"][0]["listen_port"], 2080)
        self.assertNotIn("experimental", config)


class SingBoxSSConfigTest(unittest.TestCase):
    """Ensure Shadowsocks config generation is not broken."""

    def test_ss_outbound_unchanged(self):
        server = _FakeServer(
            protocol=ProxyProtocol.SHADOWSOCKS,
            host="1.2.3.4", port=8388,
            method="aes-256-gcm", password="secret",
        )
        ob = _build_singbox_ss_outbound(server)
        self.assertEqual(ob["type"], "shadowsocks")
        self.assertEqual(ob["server"], "1.2.3.4")
        self.assertEqual(ob["server_port"], 8388)
        self.assertEqual(ob["method"], "aes-256-gcm")
        self.assertEqual(ob["password"], "secret")
        self.assertFalse(ob["multiplex"]["enabled"])

    def test_ss_full_config(self):
        engine = SingBoxEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        config = engine.build_config(server)
        self.assertEqual(config["outbounds"][0]["type"], "shadowsocks")
        self.assertEqual(config["route"]["final"], "proxy")

    def test_ss_route_rule_uses_ip_is_private(self):
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        config = _generate_config(server, 1080)
        rule = config["route"]["rules"][1]
        self.assertIn("ip_is_private", rule)
        self.assertEqual(rule["ip_is_private"], True)
        self.assertNotIn("ip_cidr", rule)

    def test_ss_build_args_creates_config_file(self):
        engine = SingBoxEngine()
        engine.local_port = 1080
        server = SimpleNamespace(host="1.2.3.4", port=8388,
                                 method="aes-256-gcm", password="secret")
        args = engine.build_args(server)
        config_path = Path(args[2])
        self.assertTrue(config_path.exists())
        with open(config_path) as f:
            config = json.load(f)
        self.assertEqual(config["outbounds"][0]["type"], "shadowsocks")
        config_path.unlink(missing_ok=True)


class SingBoxTransportTest(unittest.TestCase):

    def test_tcp_returns_none(self):
        server = _FakeServer(transport="tcp", path="", host_header="")
        self.assertIsNone(_build_singbox_transport(server))

    def test_ws_with_path_and_host(self):
        server = _FakeServer(transport="ws", path="/ws", host_header="cdn.com")
        tr = _build_singbox_transport(server)
        self.assertEqual(tr["type"], "ws")
        self.assertEqual(tr["path"], "/ws")
        self.assertEqual(tr["headers"]["Host"], "cdn.com")

    def test_ws_without_host(self):
        server = _FakeServer(transport="ws", path="/ws", host_header="")
        tr = _build_singbox_transport(server)
        self.assertEqual(tr["type"], "ws")
        self.assertEqual(tr["path"], "/ws")
        self.assertNotIn("headers", tr)

    def test_grpc(self):
        server = _FakeServer(transport="grpc", path="svc1", host_header="")
        tr = _build_singbox_transport(server)
        self.assertEqual(tr["type"], "grpc")
        self.assertEqual(tr["service_name"], "svc1")

    def test_grpc_empty_service(self):
        server = _FakeServer(transport="grpc", path="", host_header="")
        tr = _build_singbox_transport(server)
        self.assertEqual(tr["type"], "grpc")
        self.assertNotIn("service_name", tr)


class SingBoxTunConfigTest(unittest.TestCase):

    def test_tun_mode_generates_tun_inbound_and_dns(self):
        server = _FakeServer(
            protocol=ProxyProtocol.SHADOWSOCKS,
            host="1.2.3.4", port=8388,
            method="aes-256-gcm", password="secret",
        )
        config = _generate_config(server, 1080, tun_mode=True)
        self.assertIn("dns", config)
        self.assertEqual(config["dns"]["servers"][0]["type"], "https")
        self.assertEqual(config["dns"]["servers"][0]["server"], "1.1.1.1")
        self.assertEqual(config["dns"]["servers"][1]["type"], "local")
        self.assertEqual(len(config["inbounds"]), 2)
        tun_in = config["inbounds"][0]
        self.assertEqual(tun_in["type"], "tun")
        self.assertTrue(tun_in["interface_name"].startswith("socksicle-"))
        self.assertEqual(tun_in["address"], ["172.19.0.1/30"])
        self.assertTrue(tun_in["auto_route"])
        self.assertFalse(tun_in["strict_route"])
        self.assertEqual(tun_in["stack"], "system")
        mixed_in = config["inbounds"][1]
        self.assertEqual(mixed_in["type"], "mixed")
        self.assertEqual(mixed_in["listen_port"], 1080)
        self.assertEqual(config["route"]["default_domain_resolver"], "remote-dns")
        self.assertEqual(config["route"]["rules"][0]["action"], "sniff")
        self.assertEqual(config["route"]["rules"][1]["protocol"], "dns")
        self.assertEqual(config["route"]["rules"][1]["action"], "hijack-dns")

    def test_singbox_engine_process_name_with_tun(self):
        engine = SingBoxEngine()
        self.assertEqual(engine.process_name(), "sing-box")
        engine.tun_mode = True
        self.assertEqual(engine.process_name(), "sing-box (TUN)")

    def test_singbox_binary_validates_configs(self):
        """If sing-box.exe binary is present, validate generated configs using `sing-box check`."""
        engine = SingBoxEngine()
        binary = engine.find_binary()
        if not binary or not binary.exists():
            return
        import subprocess
        for proto in (ProxyProtocol.SHADOWSOCKS, ProxyProtocol.VLESS, ProxyProtocol.VMESS, ProxyProtocol.HYSTERIA2):
            for tun in (False, True):
                srv = _FakeServer(
                    protocol=proto, host="1.2.3.4", port=443,
                    password="pass", method="aes-256-gcm", uuid="11111111-1111-1111-1111-111111111111",
                    flow="", security="none", transport="tcp", server_name="", fingerprint="",
                    public_key="", short_id="", path="", host_header=""
                )
                cfg = _generate_config(srv, 1080, tun_mode=tun)
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                    json.dump(cfg, f)
                    temp_name = f.name
                try:
                    res = subprocess.run([str(binary), "check", "-c", temp_name], capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0, f"sing-box check failed for {proto} tun={tun}: {res.stderr}")
                finally:
                    if os.path.exists(temp_name):
                        os.remove(temp_name)


if __name__ == "__main__":
    unittest.main()
