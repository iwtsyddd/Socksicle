"""Unit tests for vless:// and vmess:// link parsing."""
import base64
import json
import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.link_parser import parse_link, parse_links_from_text, _parse_vless, _parse_vmess
from utils.server_model import Server, ProxyProtocol


def _b64_encode(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip('=')


def _b64_encode_json(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip('=')


# --- VLESS link tests ---

class TestParseVlessLink:
    def test_basic_vless_reality(self):
        link = (
            "vless://abc123-uuid@1.2.3.4:443"
            "?security=reality&type=tcp&sni=example.com"
            "&fp=chrome&pbk=PUBLIC_KEY&sid=SHORT_ID"
            "&flow=xtls-rprx-vision#My%20Server"
        )
        s = parse_link(link)
        assert s is not None
        assert s.protocol == ProxyProtocol.VLESS
        assert s.uuid == "abc123-uuid"
        assert s.host == "1.2.3.4"
        assert s.port == 443
        assert s.security == "reality"
        assert s.transport == "tcp"
        assert s.server_name == "example.com"
        assert s.fingerprint == "chrome"
        assert s.public_key == "PUBLIC_KEY"
        assert s.short_id == "SHORT_ID"
        assert s.flow == "xtls-rprx-vision"
        assert s.name == "My Server"
        assert s.key == link

    def test_vless_tls_ws(self):
        link = (
            "vless://uuid-tls@host.com:8443"
            "?security=tls&type=ws&path=/ws"
            "&host=cdn.example.com&sni=cdn.example.com"
            "#TLS%20WS"
        )
        s = parse_link(link)
        assert s is not None
        assert s.protocol == ProxyProtocol.VLESS
        assert s.security == "tls"
        assert s.transport == "ws"
        assert s.path == "/ws"
        assert s.host_header == "cdn.example.com"
        assert s.server_name == "cdn.example.com"
        assert s.name == "TLS WS"

    def test_vless_no_security(self):
        link = "vless://uuid@1.2.3.4:1080?security=none&type=tcp#NoSec"
        s = parse_link(link)
        assert s is not None
        assert s.security == "none"
        assert s.transport == "tcp"

    def test_vless_grpc(self):
        link = (
            "vless://uuid@grpc.server:443"
            "?security=tls&type=grpc&serviceName=grpc-service"
            "&sni=grpc.server&fp=firefox#Grpc"
        )
        s = parse_link(link)
        assert s is not None
        assert s.transport == "grpc"
        assert s.path == "grpc-service"
        assert s.fingerprint == "firefox"

    def test_vless_empty_uuid(self):
        link = "vless://@1.2.3.4:443?security=tls#Empty"
        s = parse_link(link)
        assert s is not None
        assert s.uuid == ""

    def test_vless_no_name_defaults(self):
        link = "vless://uuid@1.2.3.4:443?security=tcp"
        s = parse_link(link, default_name="Default")
        assert s is not None
        assert s.name == "Default"

    def test_vless_missing_port(self):
        link = "vless://uuid@1.2.3.4?security=tls#Bad"
        s = parse_link(link)
        assert s is None

    def test_vless_malformed(self):
        assert parse_link("vless://") is None
        assert parse_link("vless://garbage") is None


# --- VMess link tests ---

class TestParseVmessLink:
    def test_basic_vmess_tls(self):
        vmess_obj = {
            "v": "2",
            "ps": "VMess Server",
            "add": "5.6.7.8",
            "port": "443",
            "id": "uuid-vmess-123",
            "aid": "0",
            "scy": "auto",
            "net": "tcp",
            "tls": "tls",
            "sni": "sni.example.com",
            "fp": "chrome",
            "host": "",
            "path": "",
        }
        link = "vmess://" + _b64_encode_json(vmess_obj)
        s = parse_link(link)
        assert s is not None
        assert s.protocol == ProxyProtocol.VMESS
        assert s.name == "VMess Server"
        assert s.host == "5.6.7.8"
        assert s.port == 443
        assert s.uuid == "uuid-vmess-123"
        assert s.alter_id == 0
        assert s.vmess_security == "auto"
        assert s.security == "tls"
        assert s.transport == "tcp"
        assert s.server_name == "sni.example.com"
        assert s.fingerprint == "chrome"
        assert s.key == link

    def test_vmess_ws(self):
        vmess_obj = {
            "v": "2",
            "ps": "WS VMess",
            "add": "ws.host.com",
            "port": "80",
            "id": "uuid-ws",
            "aid": "2",
            "scy": "chacha20-poly1305",
            "net": "ws",
            "tls": "",
            "sni": "",
            "fp": "firefox",
            "host": "ws.host.com",
            "path": "/vmess",
        }
        link = "vmess://" + _b64_encode_json(vmess_obj)
        s = parse_link(link)
        assert s is not None
        assert s.transport == "ws"
        assert s.security == "none"
        assert s.host_header == "ws.host.com"
        assert s.path == "/vmess"
        assert s.alter_id == 2
        assert s.vmess_security == "chacha20-poly1305"

    def test_vmess_no_ps(self):
        vmess_obj = {
            "v": "2",
            "ps": "",
            "add": "1.1.1.1",
            "port": "443",
            "id": "uuid-nops",
            "aid": "0",
            "scy": "auto",
            "net": "tcp",
            "tls": "tls",
        }
        link = "vmess://" + _b64_encode_json(vmess_obj)
        s = parse_link(link, default_name="Fallback")
        assert s is not None
        assert s.name == "Fallback"

    def test_vmess_malformed_json(self):
        link = "vmess://" + _b64_encode("not valid json {{{")
        s = parse_link(link)
        assert s is None

    def test_vmess_garbage_base64(self):
        assert parse_link("vmess://!!!invalid!!!") is None


# --- Backward compatibility ---

class TestFromLinkBackwardCompat:
    def test_ss_link_still_works(self):
        """Server.from_link should still handle ss:// links."""
        from utils.ss_parser import decode_ss_link
        inner = _b64_encode("aes-256-gcm:testpass@1.2.3.4:8388")
        link = f"ss://{inner}#SS%20Test"
        s = Server.from_link(link)
        assert s is not None
        assert s.protocol == ProxyProtocol.SHADOWSOCKS
        assert s.method == "aes-256-gcm"
        assert s.password == "testpass"
        assert s.name == "SS Test"

    def test_vless_link_via_from_link(self):
        link = "vless://uuid@1.2.3.4:443?security=tls#Vless"
        s = Server.from_link(link)
        assert s is not None
        assert s.protocol == ProxyProtocol.VLESS

    def test_vmess_link_via_from_link(self):
        vmess_obj = {
            "v": "2", "ps": "VM", "add": "1.2.3.4", "port": "443",
            "id": "uuid", "aid": "0", "scy": "auto", "net": "tcp", "tls": "tls",
        }
        link = "vmess://" + _b64_encode_json(vmess_obj)
        s = Server.from_link(link)
        assert s is not None
        assert s.protocol == ProxyProtocol.VMESS

    def test_from_link_none(self):
        assert Server.from_link(None) is None
        assert Server.from_link("") is None


# --- Server model round-trip tests ---

class TestServerModelRoundTrip:
    def test_vless_to_dict_from_dict(self):
        s = Server(
            key="vless://...", name="V", host="h", port=443,
            protocol=ProxyProtocol.VLESS, uuid="u",
            security="reality", transport="tcp", flow="xtls-rprx-vision",
            server_name="sni", fingerprint="chrome",
            public_key="pbk", short_id="sid",
        )
        d = s.to_dict()
        assert d["protocol"] == "vless"
        assert d["uuid"] == "u"
        assert d["security"] == "reality"
        s2 = Server.from_dict(d)
        assert s2.protocol == ProxyProtocol.VLESS
        assert s2.uuid == "u"
        assert s2.security == "reality"
        assert s2.short_id == "sid"

    def test_vmess_to_dict_from_dict(self):
        s = Server(
            key="vmess://...", name="V", host="h", port=443,
            protocol=ProxyProtocol.VMESS, uuid="u",
            alter_id=2, vmess_security="chacha20-poly1305",
            transport="ws", path="/ws", host_header="cdn.com",
        )
        d = s.to_dict()
        assert d["protocol"] == "vmess"
        assert d["alter_id"] == 2
        s2 = Server.from_dict(d)
        assert s2.protocol == ProxyProtocol.VMESS
        assert s2.alter_id == 2
        assert s2.vmess_security == "chacha20-poly1305"
        assert s2.path == "/ws"

    def test_ss_to_dict_unchanged(self):
        s = Server(
            key="ss://...", name="S", host="h", port=443,
            method="aes-256-gcm", password="pw",
        )
        d = s.to_dict()
        assert "protocol" not in d
        assert "uuid" not in d
        assert d["method"] == "aes-256-gcm"

    def test_unique_key_vless(self):
        s1 = Server(protocol=ProxyProtocol.VLESS, uuid="u", host="h", port=443)
        s2 = Server(protocol=ProxyProtocol.VLESS, uuid="u", host="h", port=443)
        s3 = Server(protocol=ProxyProtocol.VLESS, uuid="other", host="h", port=443)
        assert s1.unique_key == s2.unique_key
        assert s1.unique_key != s3.unique_key

    def test_display_protocol(self):
        s = Server(protocol=ProxyProtocol.VLESS)
        assert s.display_protocol == "VLESS"
        s2 = Server(protocol=ProxyProtocol.VMESS)
        assert s2.display_protocol == "VMESS"
        s3 = Server(protocol=ProxyProtocol.SHADOWSOCKS)
        assert s3.display_protocol == "SHADOWSOCKS"


# --- parse_links_from_text ---

class TestParseLinksFromText:
    def test_extracts_links(self):
        text = (
            "Some garbage\n"
            "vless://uuid@1.2.3.4:443?security=tls#V\n"
            "more text\n"
            "vmess://" + _b64_encode_json({"v":"2","ps":"","add":"h","port":"443","id":"u","aid":"0","scy":"auto","net":"tcp","tls":""}) + "\n"
        )
        links = parse_links_from_text(text)
        assert len(links) == 2
        assert links[0].startswith("vless://")
        assert links[1].startswith("vmess://")

    def test_no_links(self):
        assert parse_links_from_text("nothing here") == []
        assert parse_links_from_text("") == []


# --- Optimizations tests ---

class TestOptimizations:
    def test_is_private_host_lru_cached(self):
        from utils.server_model import is_private_host
        is_private_host.cache_clear()
        assert is_private_host("127.0.0.1") is True
        assert is_private_host("127.0.0.1") is True
        info = is_private_host.cache_info()
        assert info.hits >= 1
        assert info.maxsize == 1024

    def test_parse_mbps_formats(self):
        from utils.link_parser import _parse_mbps
        assert _parse_mbps("100Mbps") == 100
        assert _parse_mbps("50mb/s") == 50
        assert _parse_mbps("10M") == 10
        assert _parse_mbps("2000kbps") == 2000
        assert _parse_mbps("500k") == 500
        assert _parse_mbps("") == 0
        assert _parse_mbps(None) == 0
        assert _parse_mbps("invalid") == 0

    def test_link_parser_is_private_flag(self):
        vless_priv = parse_link("vless://uuid@192.168.1.1:443?security=none#Priv")
        assert vless_priv is not None
        assert vless_priv.is_private is True

        vless_pub = parse_link("vless://uuid@8.8.8.8:443?security=none#Pub")
        assert vless_pub is not None
        assert vless_pub.is_private is False

