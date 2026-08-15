import base64
import binascii
import ipaddress
import json
import logging
import os
import re
import tempfile
import time
import uuid
import hashlib
import urllib.error
import urllib.request
from urllib.parse import quote, unquote, urlparse

from .platform_utils import get_config_dir
from . import twinsock

log = logging.getLogger(__name__)


# --- User-Agent presets ---

USER_AGENT_PRESETS = {
    "socksicle": "Socksicle/1.0",
    "happ": "Happ/4.0.5",
    "hiddify": "HiddifyNext/2.5.7",
    "incy": "InCY/1.0.0",
    "karing": "Karing/1.0.8",
    "clash": "ClashForWindows/0.20.39",
    "curl": "curl/7.88.0",
    "nekoray": "NekoBox/PC/2.1.0 (Prefer ClashMeta Format)",
    "v2rayng": "v2rayNG/1.8.12",
    "mihomo": "clash-meta",
    "shadowsocks": "ShadowsocksWindows/4.4.1.0",
    "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
}


def _generate_hwid():
    """Generate a deterministic HWID based on machine identifiers."""
    raw = str(uuid.getnode()) + "socksicle-hwid"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _subscriptions_path():
    return get_config_dir() / "subscriptions.json"


def _decode_maybe_base64(value: str) -> str:
    """Return UTF-8 text for 'base64:<...>' header values (de-facto panel convention);
    any other value passes through unchanged."""
    if not value.startswith("base64:"):
        return value
    body = value[len("base64:"):]
    try:
        return base64.b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return value


def _extract_metadata(response):
    """Extract all supported subscription headers into a metadata dict."""
    meta = {}

    # Traffic info
    info_header = response.headers.get('Subscription-Userinfo')
    if info_header:
        parts = dict(
            item.split('=', 1)
            for item in info_header.replace(' ', '').split(';')
            if '=' in item
        )
        try:
            meta['traffic'] = {
                'used': int(parts.get('upload', 0)) + int(parts.get('download', 0)),
                'total': int(parts.get('total', 0)),
                'expire': int(parts.get('expire', 0)),
            }
        except (ValueError, TypeError):
            meta['traffic'] = {'used': 0, 'total': 0, 'expire': 0}

    # Profile metadata headers
    for header_name, key, converter in [
        ('Profile-Update-Interval', 'profile_update_interval', int),
        ('Profile-Title', 'profile_title', str),
        ('Profile-Description', 'description', str),
        ('Support-URL', 'support_url', str),
        ('Profile-Web-Page-URL', 'profile_web_page_url', str),
        ('Announce', 'announce', str),
        ('Content-Disposition', 'content_disposition', str),
    ]:
        raw = response.headers.get(header_name)
        if raw:
            try:
                meta[key] = converter(raw)
            except (ValueError, TypeError):
                meta[key] = raw

    # Panels base64-encode UTF-8 header values with a "base64:" prefix
    for key in ('profile_title', 'announce', 'content_disposition', 'description'):
        if key in meta:
            meta[key] = _decode_maybe_base64(meta[key])

    return meta


def _extract_description(headers, decoded_lines, announce, meta):
    """Derive a subscription description from headers or body preamble."""
    desc = meta.get('description')
    if desc and not desc.startswith("base64:"):
        return desc
    if announce and not announce.startswith("base64:"):
        if announce.strip() and not re.fullmatch(r'https?://\S*', announce):
            return announce
    preamble = []
    for line in decoded_lines:
        line = line.strip()
        if line.startswith(('ss://', 'vless://', 'vmess://')):
            break
        if not line or line.startswith("base64:"):
            continue
        preamble.append(line)
        if len(preamble) >= 10:
            break
    return " ".join(preamble)


def _try_parse_sip008_json(content):
    """Try to parse content as SIP008 JSON. Returns (ss_links, meta) or None."""
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict) or data.get('version') != 1:
        return None

    servers = data.get('servers', [])
    if not isinstance(servers, list):
        return None

    ss_links = []
    for srv in servers:
        if not isinstance(srv, dict):
            continue
        host = srv.get('server', '')
        port = srv.get('server_port', 443)
        method = srv.get('method', '')
        password = srv.get('password', '')
        plugin = srv.get('plugin', '')
        plugin_opts = srv.get('plugin_opts', '')
        remarks = srv.get('remarks', '')

        if not host or not method:
            continue

        # Build ss:// link in SIP002 format
        userinfo_b64 = base64.urlsafe_b64encode(
            f"{method}:{password}".encode()
        ).decode().rstrip('=')

        link = f"ss://{userinfo_b64}@{host}:{port}"

        # Add plugin if present
        if plugin:
            raw_plugin = plugin
            if plugin_opts:
                raw_plugin += ";" + plugin_opts
            # Escape special chars, then percent-encode
            escaped = raw_plugin.replace('\\', '\\\\').replace(';', '\\;').replace('=', '\\=')
            link += "/?plugin=" + quote(escaped, safe='')

        if remarks:
            link += "#" + quote(remarks, safe='')

        ss_links.append(link)

    meta = {}
    if 'bytes_used' in data or 'bytes_remaining' in data:
        try:
            used = int(data.get('bytes_used', 0))
            remaining = int(data.get('bytes_remaining', 0))
            meta['traffic'] = {
                'used': used,
                'total': used + remaining,
                'expire': 0,
            }
        except (ValueError, TypeError):
            meta['traffic'] = {'used': 0, 'total': 0, 'expire': 0}

    return ss_links, meta


def parse_subscription(url, settings=None):
    """Fetch and parse a shadowsocks subscription.

    Args:
        url: Subscription URL.
        settings: Optional dict with keys:
            - user_agent_key: str key from USER_AGENT_PRESETS
            - fake_hwid: bool whether to send X-hwid header
            - hwid_value: str custom HWID value (if empty, auto-generate)

    Returns (ss_links, metadata_dict).

    Supports:
    - Base64-encoded link lists (standard)
    - SIP008 JSON format
    - Extended HTTP headers for metadata
    """
    settings = settings or {}
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("https", "http"):
        log.warning("Blocked subscription URL with scheme: %s", parsed.scheme)
        return [], {}
    if parsed.scheme.lower() == "http":
        log.warning("Subscription URL uses HTTP (not HTTPS): %s", url)
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            log.warning("Blocked subscription URL pointing to private/local IP: %s", url)
            return [], {}
    except (ValueError, AttributeError):
        pass  # hostname is a domain name or None — OK
    try:
        # Build User-Agent
        ua_key = settings.get("user_agent_key", "socksicle")
        user_agent = USER_AGENT_PRESETS.get(ua_key, USER_AGENT_PRESETS["socksicle"])

        # Build headers
        headers = {'User-Agent': user_agent}

        # HWID header
        if settings.get("fake_hwid", False):
            hwid_val = settings.get("hwid_value", "").strip()
            if not hwid_val:
                hwid_val = _generate_hwid()
            headers['X-hwid'] = hwid_val

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            raw_content = response.read().decode('utf-8').strip()
            content_type = response.headers.get('Content-Type', '')

            # Extract extended metadata from headers
            meta = _extract_metadata(response)

            # Check for SIP008 JSON format
            is_json = (
                'application/json' in content_type
                or (raw_content.startswith('{') and raw_content.endswith('}'))
            )
            if is_json:
                result = _try_parse_sip008_json(raw_content)
                if result is not None:
                    ss_links, json_meta = result
                    meta.update(json_meta)
                    return ss_links, meta

            # Standard base64 format
            try:
                decoded_content = base64.b64decode(
                    raw_content + '=' * (-len(raw_content) % 4)
                ).decode('utf-8')
            except (binascii.Error, ValueError, UnicodeDecodeError) as e:
                log.warning("Base64 decode failed, using raw content: %s", e)
                decoded_content = raw_content

            decoded_lines = decoded_content.splitlines()
            if 'description' not in meta or not meta['description']:
                meta['description'] = _extract_description(
                    headers, decoded_lines, meta.get('announce', ''), meta)

            supported_prefixes = ('ss://', 'vless://', 'vmess://')
            links = [
                line for line in decoded_lines
                if line.strip().startswith(supported_prefixes)
            ]

            return links, meta
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        log.error("Subscription fetch/parse error for URL: %s — %s", url, e)
        return [], {}


def _seal_subscription(sub):
    d = dict(sub)
    servers = []
    for s in d.get("servers", []):
        s_dict = s.to_dict() if hasattr(s, "to_dict") else dict(s)
        servers.append(twinsock.seal_dict("subscriptions", s_dict, twinsock.SECRET_FIELDS))
    d["servers"] = servers
    d["url"] = twinsock.encrypt_field("subscriptions", d.get("url", ""))
    return d


def _retire_foreign(path):
    if not os.path.exists(path):
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        os.replace(path, f"{path}.foreign-{stamp}.json")
    except OSError as e:
        log.error("Failed to retire foreign config %s: %s", path, e)


def save_subscriptions(subs):
    path = _subscriptions_path()
    while True:
        try:
            sealed = [_seal_subscription(sub) for sub in subs]
            break
        except twinsock.VaultError as e:
            if str(e) != "foreign":
                raise
            log.warning("vault: foreign config, retiring subscriptions.json and starting fresh")
            _retire_foreign(str(path))
            twinsock.drop_foreign()
            continue
    with tempfile.NamedTemporaryFile(
            mode='w', dir=str(path.parent), delete=False,
            encoding="utf-8", suffix='.tmp') as f:
        json.dump(sealed, f)
        tmp_name = f.name
    try:
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise
    twinsock.file_saved("subscriptions.json")


def load_subscriptions():
    path = _subscriptions_path()
    if not path.exists():
        return []
    twinsock.file_intact("subscriptions.json")
    try:
        with open(path, 'r', encoding="utf-8", errors="replace") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        log.error("Failed to load subscriptions: %s", e)
        return []
    if not isinstance(raw, list):
        return []
    subs = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        try:
            d = twinsock.unseal_dict("subscriptions", d, ("url",))
        except twinsock.VaultError as e:
            log.warning("vault: subscriptions unusable on this machine: %s", e)
            return []
        servers = []
        for s in d.get("servers", []):
            if isinstance(s, dict):
                try:
                    s = twinsock.unseal_dict("subscriptions", s, twinsock.SECRET_FIELDS)
                except twinsock.VaultError as e:
                    log.warning("vault: subscriptions unusable on this machine: %s", e)
                    return []
            servers.append(s)
        d["servers"] = servers
        subs.append(d)
    if twinsock.migration_occurred():
        save_subscriptions(subs)
    return subs
