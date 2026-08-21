"""Unit tests for subscription multi-node parsing and deduplication."""
import base64
import json
from utils.server_model import Server, ProxyProtocol
from utils.subscription_manager import SubscriptionManager
import utils.sub_manager as sm


def test_multinode_same_host_preserved(tmp_path, monkeypatch):
    """Ensure nodes with same host/uuid but different names/flags (e.g. Google DE, Google NL) are preserved."""
    monkeypatch.setattr("utils.sub_manager.get_config_dir", lambda: tmp_path)

    de_link = "vless://uuid-123@google.com:443?security=reality&sni=de.google.com#Google%20%F0%9F%87%A9%F0%9F%87%AA"
    nl_link = "vless://uuid-123@google.com:443?security=reality&sni=nl.google.com#Google%20%F0%9F%87%B3%F0%9F%87%B1"
    us_link = "vless://uuid-123@google.com:443?security=reality&sni=us.google.com#Google%20%F0%9F%87%BA%F0%9F%87%B8"

    raw_links = f"{de_link}\n{nl_link}\n{us_link}\n"
    b64_sub = base64.b64encode(raw_links.encode("utf-8")).decode("utf-8")

    # Mock parse_subscription to return our links
    monkeypatch.setattr("utils.subscription_manager.parse_subscription",
                        lambda url, settings: ([de_link, nl_link, us_link], {"profile_title": "Google VPN"}))

    sub_mgr = SubscriptionManager()
    ok = sub_mgr.add("Google Sub", "https://example.com/sub")
    assert ok is True

    servers = sub_mgr.get_servers("Google Sub")
    assert len(servers) == 3
    names = [s.name for s in servers]
    assert "Google 🇩🇪" in names
    assert "Google 🇳🇱" in names
    assert "Google 🇺🇸" in names


def test_base64_multiline_with_whitespace_decoding(tmp_path, monkeypatch):
    """Test base64 subscription decoding with wrapped lines and whitespace."""
    raw_text = "vless://u1@h1:443#N1\nvless://u2@h2:443#N2\n"
    # Encode and insert linebreaks/spaces inside base64
    b64 = base64.b64encode(raw_text.encode("utf-8")).decode("utf-8")
    b64_with_spaces = b64[:10] + "\r\n  " + b64[10:]

    class DummyResp:
        headers = {}
        def read(self):
            return b64_with_spaces.encode("utf-8")
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout: DummyResp())

    links, meta = sm.parse_subscription("https://valid-sub.example.com/sub")
    assert len(links) == 2
    assert links[0] == "vless://u1@h1:443#N1"
    assert links[1] == "vless://u2@h2:443#N2"
