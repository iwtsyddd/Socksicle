"""Unit tests for ss_parser and sub_manager."""
import base64
import json
import pytest
from unittest.mock import patch, MagicMock
from urllib.parse import quote

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.ss_parser import decode_ss_link, _parse_plugin, _unescape_plugin_string


# --- Helper to build ss:// links ---

def _b64_encode(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip('=')


def _make_legacy_link(method, password, host, port, tag=""):
    """Legacy whole-URI base64: ss://BASE64(method:password)@host:port#tag"""
    payload = _b64_encode(f"{method}:{password}@{host}:{port}")
    link = f"ss://{payload}"
    if tag:
        link += f"#{quote(tag)}"
    return link


def _make_sip002_link(method, password, host, port, tag="", plugin=""):
    """SIP002 base64 userinfo: ss://BASE64(method:password)@host:port/?plugin=...#tag"""
    payload = _b64_encode(f"{method}:{password}")
    link = f"ss://{payload}@{host}:{port}"
    if plugin:
        link += f"/?plugin={quote(plugin, safe='')}"
    if tag:
        link += f"#{quote(tag)}"
    return link


def _make_aead2022_link(method, password, host, port, tag=""):
    """AEAD-2022 plain userinfo: ss://method:password@host:port#tag"""
    link = f"ss://{method}:{quote(password, safe='')}"
    link += f"@{host}:{port}"
    if tag:
        link += f"#{quote(tag)}"
    return link


# --- Tests for _unescape_plugin_string ---

class TestUnescapePluginString:
    def test_no_escapes(self):
        assert _unescape_plugin_string("abc") == "abc"

    def test_escape_semicolon(self):
        assert _unescape_plugin_string("abc\\;def") == "abc;def"

    def test_escape_equals(self):
        assert _unescape_plugin_string("a\\=b") == "a=b"

    def test_escape_backslash(self):
        assert _unescape_plugin_string("a\\\\b") == "a\\b"

    def test_multiple_escapes(self):
        assert _unescape_plugin_string("a\\;b\\=c\\\\d") == "a;b=c\\d"


# --- Tests for _parse_plugin ---

class TestParsePlugin:
    def test_plugin_name_only(self):
        name, opts = _parse_plugin("v2ray-plugin;server")
        assert name == "v2ray-plugin"
        assert opts == "server"

    def test_plugin_with_options(self):
        name, opts = _parse_plugin("obfs-local;obfs=http;obfs-host=example.com")
        assert name == "obfs-local"
        assert opts == "obfs=http;obfs-host=example.com"

    def test_escaped_plugin(self):
        name, opts = _parse_plugin("obfs-local\\;obfs\\=http")
        assert name == "obfs-local"
        assert opts == "obfs=http"


# --- Tests for decode_ss_link ---

class TestDecodeLegacyLink:
    def test_basic_legacy(self):
        link = _make_legacy_link("aes-256-gcm", "testpass", "1.2.3.4", 8388)
        result = decode_ss_link(link)
        assert result is not None
        assert result['method'] == "aes-256-gcm"
        assert result['password'] == "testpass"
        assert result['server'] == "1.2.3.4"
        assert result['port'] == 8388

    def test_legacy_with_tag(self):
        link = _make_legacy_link("chacha20-ietf-poly1305", "mypass", "10.0.0.1", 443, tag="My Server")
        result = decode_ss_link(link)
        assert result['tag'] == "My Server"
        assert result['method'] == "chacha20-ietf-poly1305"

    def test_legacy_with_percent_encoded_tag(self):
        link = _make_legacy_link("aes-128-gcm", "pw", "host.com", 1080, tag="Server #1")
        result = decode_ss_link(link)
        assert result['tag'] == "Server #1"


class TestDecodeSIP002Link:
    def test_basic_sip002(self):
        link = _make_sip002_link("aes-256-gcm", "testpass", "1.2.3.4", 8388)
        result = decode_ss_link(link)
        assert result is not None
        assert result['method'] == "aes-256-gcm"
        assert result['password'] == "testpass"
        assert result['server'] == "1.2.3.4"
        assert result['port'] == 8388

    def test_sip002_with_tag(self):
        link = _make_sip002_link("aes-256-gcm", "pw", "host.com", 443, tag="Server #1")
        result = decode_ss_link(link)
        assert result['tag'] == "Server #1"

    def test_sip002_with_plugin_obfs(self):
        plugin = "obfs-local;obfs=http;obfs-host=www.example.com"
        link = _make_sip002_link("aes-256-gcm", "pw", "host.com", 443, plugin=plugin)
        result = decode_ss_link(link)
        assert result is not None
        assert result['plugin'] == "obfs-local"
        assert result['plugin_opts'] == "obfs=http;obfs-host=www.example.com"

    def test_sip002_with_plugin_v2ray(self):
        plugin = "v2ray-plugin;server;tls;host=github.com"
        link = _make_sip002_link("chacha20-ietf-poly1305", "secret", "my.server.com", 8888, plugin=plugin, tag="V2Ray")
        result = decode_ss_link(link)
        assert result['plugin'] == "v2ray-plugin"
        assert result['plugin_opts'] == "server;tls;host=github.com"
        assert result['tag'] == "V2Ray"

    def test_sip002_with_plugin_no_opts(self):
        plugin = "v2ray-plugin;server"
        link = _make_sip002_link("aes-256-gcm", "pw", "1.2.3.4", 443, plugin=plugin)
        result = decode_ss_link(link)
        assert result['plugin'] == "v2ray-plugin"
        assert result['plugin_opts'] == "server"


class TestDecodeAEAD2022Link:
    def test_basic_aead2022(self):
        link = _make_aead2022_link("2022-blake3-aes-256-gcm", "testPasswordPSK==", "1.2.3.4", 8388)
        result = decode_ss_link(link)
        assert result is not None
        assert result['method'] == "2022-blake3-aes-256-gcm"
        assert result['password'] == "testPasswordPSK=="
        assert result['server'] == "1.2.3.4"
        assert result['port'] == 8388

    def test_aead2022_with_tag(self):
        link = _make_aead2022_link("2022-blake3-aes-128-gcm", "key123", "host.com", 443, tag="AEAD Server")
        result = decode_ss_link(link)
        assert result['tag'] == "AEAD Server"
        assert result['method'] == "2022-blake3-aes-128-gcm"

    def test_aead2022_with_special_password(self):
        link = _make_aead2022_link("2022-blake3-chacha20-poly1305", "abc/def+ghi==", "server.net", 8443)
        result = decode_ss_link(link)
        assert result is not None
        assert result['password'] == "abc/def+ghi=="


class TestDecodeEdgeCases:
    def test_invalid_scheme(self):
        assert decode_ss_link("http://example.com") is None

    def test_empty_string(self):
        assert decode_ss_link("") is None

    def test_none(self):
        assert decode_ss_link(None) is None

    def test_garbage_base64(self):
        assert decode_ss_link("ss://!!!invalid!!!") is None


# --- Tests for Server model ---

class TestServerModel:
    def _get_server_class(self):
        from utils.server_model import Server
        return Server

    def test_from_link_legacy(self):
        Server = self._get_server_class()
        link = _make_legacy_link("aes-256-gcm", "testpass", "1.2.3.4", 8388, tag="Test")
        s = Server.from_link(link)
        assert s is not None
        assert s.method == "aes-256-gcm"
        assert s.password == "testpass"
        assert s.host == "1.2.3.4"
        assert s.port == 8388
        assert s.name == "Test"
        assert s.key == link

    def test_from_link_sip002_with_plugin(self):
        Server = self._get_server_class()
        plugin = "obfs-local;obfs=http;obfs-host=example.com"
        link = _make_sip002_link("aes-256-gcm", "pw", "host.com", 443, plugin=plugin, tag="Obfs")
        s = Server.from_link(link)
        assert s is not None
        assert s.plugin == "obfs-local"
        assert s.plugin_opts == "obfs=http;obfs-host=example.com"

    def test_from_link_aead2022(self):
        Server = self._get_server_class()
        link = _make_aead2022_link("2022-blake3-aes-256-gcm", "psk123", "host.com", 443, tag="AEAD22")
        s = Server.from_link(link)
        assert s is not None
        assert s.method == "2022-blake3-aes-256-gcm"
        assert s.password == "psk123"

    def test_from_dict_with_plugin(self):
        Server = self._get_server_class()
        d = {
            "key": "ss://...", "name": "Test", "host": "h.com", "port": "443",
            "method": "aes-256-gcm", "password": "pw",
            "plugin": "v2ray-plugin", "plugin_opts": "server;tls"
        }
        s = Server.from_dict(d)
        assert s.plugin == "v2ray-plugin"
        assert s.plugin_opts == "server;tls"

    def test_to_dict_with_plugin(self):
        Server = self._get_server_class()
        s = Server(key="k", name="n", host="h", port=443, method="m", password="p",
                   plugin="v2ray-plugin", plugin_opts="server")
        d = s.to_dict()
        assert d['plugin'] == "v2ray-plugin"
        assert d['plugin_opts'] == "server"

    def test_to_dict_no_plugin_omits_fields(self):
        Server = self._get_server_class()
        s = Server(key="k", name="n", host="h", port=443, method="m", password="p")
        d = s.to_dict()
        assert 'plugin' not in d
        assert 'plugin_opts' not in d

    def test_unique_key(self):
        Server = self._get_server_class()
        s1 = Server(host="h", port=443, method="m", password="p")
        s2 = Server(host="h", port=443, method="m", password="p")
        s3 = Server(host="h", port=443, method="m", password="other")
        assert s1.unique_key == s2.unique_key
        assert s1.unique_key != s3.unique_key


# --- Tests for SIP008 JSON parsing in sub_manager ---

class TestSIP008JSON:
    def test_valid_sip008(self):
        from utils.sub_manager import _try_parse_sip008_json
        data = {
            "version": 1,
            "servers": [
                {
                    "id": "test-id",
                    "remarks": "Test Server",
                    "server": "example.com",
                    "server_port": 8388,
                    "password": "testpass",
                    "method": "chacha20-ietf-poly1305",
                }
            ],
            "bytes_used": 1073741824,
            "bytes_remaining": 5368709120,
        }
        ss_links, meta = _try_parse_sip008_json(json.dumps(data))
        assert len(ss_links) == 1
        assert "example.com" in ss_links[0]
        assert meta['traffic']['used'] == 1073741824
        assert meta['traffic']['total'] == 1073741824 + 5368709120

    def test_sip008_with_plugin(self):
        from utils.sub_manager import _try_parse_sip008_json
        data = {
            "version": 1,
            "servers": [
                {
                    "remarks": "With Plugin",
                    "server": "host.com",
                    "server_port": 443,
                    "password": "pw",
                    "method": "aes-256-gcm",
                    "plugin": "obfs-local",
                    "plugin_opts": "obfs=http;obfs-host=cdn.com",
                }
            ],
        }
        ss_links, meta = _try_parse_sip008_json(json.dumps(data))
        assert len(ss_links) == 1
        # The link should contain plugin info
        assert "plugin=" in ss_links[0]

    def test_invalid_json(self):
        from utils.sub_manager import _try_parse_sip008_json
        result = _try_parse_sip008_json("not json at all")
        assert result is None

    def test_wrong_version(self):
        from utils.sub_manager import _try_parse_sip008_json
        data = {"version": 2, "servers": []}
        result = _try_parse_sip008_json(json.dumps(data))
        assert result is None

    def test_no_servers(self):
        from utils.sub_manager import _try_parse_sip008_json
        data = {"version": 1, "servers": []}
        ss_links, meta = _try_parse_sip008_json(json.dumps(data))
        assert len(ss_links) == 0


# --- Tests for metadata extraction ---

class TestMetadataExtraction:
    def _make_response(self, headers):
        resp = MagicMock()
        resp.headers = headers
        return resp

    def test_traffic_header(self):
        from utils.sub_manager import _extract_metadata
        resp = self._make_response({
            'Subscription-Userinfo': 'upload=1000; download=2000; total=5000; expire=1700000000'
        })
        meta = _extract_metadata(resp)
        assert meta['traffic']['used'] == 3000
        assert meta['traffic']['total'] == 5000
        assert meta['traffic']['expire'] == 1700000000

    def test_profile_headers(self):
        from utils.sub_manager import _extract_metadata
        resp = self._make_response({
            'Profile-Title': 'My Provider',
            'Profile-Update-Interval': '24',
            'Support-URL': 'https://support.example.com',
            'Announce': 'Server maintenance on Friday',
        })
        meta = _extract_metadata(resp)
        assert meta['profile_title'] == 'My Provider'
        assert meta['profile_update_interval'] == 24
        assert meta['support_url'] == 'https://support.example.com'
        assert meta['announce'] == 'Server maintenance on Friday'

    def test_no_headers(self):
        from utils.sub_manager import _extract_metadata
        resp = self._make_response({})
        meta = _extract_metadata(resp)
        assert meta == {}


# --- Tests for base64 header value decoding ---

class TestDecodeMaybeBase64:
    def test_plaintext_passthrough(self):
        from utils.sub_manager import _decode_maybe_base64
        assert _decode_maybe_base64("My Provider") == "My Provider"
        assert _decode_maybe_base64("") == ""

    def test_decodes_base64(self):
        from utils.sub_manager import _decode_maybe_base64
        assert _decode_maybe_base64("base64:VGVzdA==") == "Test"

    def test_undecodable_passthrough(self):
        from utils.sub_manager import _decode_maybe_base64
        assert _decode_maybe_base64("base64:!!!not-b64!!!") == "base64:!!!not-b64!!!"

    def test_decodes_base64_utf8(self):
        from utils.sub_manager import _decode_maybe_base64
        encoded = base64.b64encode("✦ Ínfinity".encode()).decode()
        assert _decode_maybe_base64("base64:" + encoded) == "✦ Ínfinity"


# --- Tests for description extraction ---

class TestExtractDescription:
    def test_header_description_beats_announce(self):
        from utils.sub_manager import _extract_description
        meta = {'description': 'From header', 'announce': 'Announce text'}
        result = _extract_description({}, ['ss://a@b:443'], meta['announce'], meta)
        assert result == 'From header'

    def test_undecodable_header_description_skipped(self):
        from utils.sub_manager import _extract_description
        meta = {'description': 'base64:!!!bad!!!', 'announce': 'Announce text'}
        result = _extract_description({}, ['ss://a@b:443'], meta['announce'], meta)
        assert result == 'Announce text'

    def test_announce_url_skipped(self):
        from utils.sub_manager import _extract_description
        meta = {'announce': 'https://example.com/news'}
        result = _extract_description({}, ['ss://a@b:443'], meta['announce'], meta)
        assert result == ''
        result = _extract_description({}, ['Welcome aboard', 'ss://a@b:443'],
                                      meta['announce'], meta)
        assert result == 'Welcome aboard'

    def test_announce_text_used(self):
        from utils.sub_manager import _extract_description
        result = _extract_description({}, ['ss://a@b:443'], 'Server maintenance on Friday', {})
        assert result == 'Server maintenance on Friday'

    def test_announce_base64_skipped(self):
        from utils.sub_manager import _extract_description
        result = _extract_description({}, ['ss://a@b:443'], 'base64:!!!bad!!!', {})
        assert result == ''

    def test_body_preamble_used(self):
        from utils.sub_manager import _extract_description
        lines = ['First line', '', 'base64:!!!skip!!!', 'Second line',
                 'ss://a@b:443', 'ss://c@d:444']
        result = _extract_description({}, lines, '', {})
        assert result == 'First line Second line'

    def test_all_links_no_description(self):
        from utils.sub_manager import _extract_description
        result = _extract_description({}, ['ss://a@b:443', 'vless://x@y:443'], '', {})
        assert result == ''

    def test_preamble_capped_at_ten_lines(self):
        from utils.sub_manager import _extract_description
        lines = [f"line {i}" for i in range(15)] + ['ss://a@b:443']
        result = _extract_description({}, lines, '', {})
        assert result == ' '.join(f"line {i}" for i in range(10))


# --- Tests for parse_subscription metadata integration ---

class TestParseSubscriptionMetadata:
    _LINK = "ss://YWVzLTI1Ni1nY206cHc@1.2.3.4:8388"

    def _mock_urlopen(self, body, headers):
        import urllib.request
        from utils import sub_manager
        resp = MagicMock()
        resp.read.return_value = body.encode()
        resp.headers = headers
        resp.__enter__.return_value = resp
        return patch.object(sub_manager.urllib.request, 'urlopen', return_value=resp)

    def test_header_description_and_decoded_title(self):
        from utils import sub_manager
        enc = lambda s: 'base64:' + base64.b64encode(s.encode()).decode()
        headers = {
            'Profile-Title': enc('My Provider'),
            'Announce': enc('Server maintenance on Friday'),
            'Profile-Description': enc('Premium service, 4K ready'),
        }
        body = base64.b64encode(self._LINK.encode()).decode()
        with self._mock_urlopen(body, headers):
            links, meta = sub_manager.parse_subscription('https://example.com/sub')
        assert len(links) == 1
        assert meta['profile_title'] == 'My Provider'
        assert meta['announce'] == 'Server maintenance on Friday'
        assert meta['description'] == 'Premium service, 4K ready'

    def test_announce_becomes_description_without_header(self):
        from utils import sub_manager
        enc = lambda s: 'base64:' + base64.b64encode(s.encode()).decode()
        headers = {'Announce': enc('Welcome to Infinity')}
        body = base64.b64encode(self._LINK.encode()).decode()
        with self._mock_urlopen(body, headers):
            links, meta = sub_manager.parse_subscription('https://example.com/sub')
        assert meta['announce'] == 'Welcome to Infinity'
        assert meta['description'] == 'Welcome to Infinity'

    def test_body_preamble_becomes_description(self):
        from utils import sub_manager
        text = "Welcome to the club\nss://a@b:443"
        body = base64.b64encode(text.encode()).decode()
        with self._mock_urlopen(body, {}):
            links, meta = sub_manager.parse_subscription('https://example.com/sub')
        assert meta['description'] == 'Welcome to the club'
