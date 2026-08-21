import pytest
from utils.server_model import Server, ProxyProtocol
from utils.engines.singbox_engine import _build_singbox_dns_server, _generate_config as _gen_singbox
from utils.engines.xray_engine import _generate_config as _gen_xray


def test_build_singbox_dns_server_doh():
    srv = _build_singbox_dns_server("https://dns.adguard-dns.com/dns-query", "remote-dns", "proxy")
    assert srv["type"] == "https"
    assert srv["server"] == "dns.adguard-dns.com"
    assert srv["path"] == "/dns-query"
    assert srv["detour"] == "proxy"


def test_build_singbox_dns_server_dot():
    srv = _build_singbox_dns_server("tls://1.1.1.1", "remote-dns", "proxy")
    assert srv["type"] == "tls"
    assert srv["server"] == "1.1.1.1"
    assert srv["server_port"] == 853


def test_build_singbox_dns_server_udp():
    srv = _build_singbox_dns_server("9.9.9.9", "remote-dns", "proxy")
    assert srv["type"] == "udp"
    assert srv["server"] == "9.9.9.9"
    assert srv["server_port"] == 53


def test_singbox_tun_custom_dns():
    server = Server(
        protocol=ProxyProtocol.VLESS,
        host="example.com",
        port=443,
        uuid="test-uuid",
    )
    cfg = _gen_singbox(server, 1080, tun_mode=True, custom_dns="https://dns.quad9.net/dns-query")
    assert "dns" in cfg
    remote_dns = cfg["dns"]["servers"][0]
    assert remote_dns["server"] == "dns.quad9.net"
    assert remote_dns["type"] == "https"


def test_xray_custom_dns():
    server = Server(
        protocol=ProxyProtocol.VLESS,
        host="example.com",
        port=443,
        uuid="test-uuid",
    )
    cfg = _gen_xray(server, 1080, custom_dns="https://dns.adguard-dns.com/dns-query")
    assert "dns" in cfg
    assert "https://dns.adguard-dns.com/dns-query" in cfg["dns"]["servers"]
