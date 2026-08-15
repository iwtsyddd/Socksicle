"""Parse vless:// and vmess:// links into Server objects."""
import base64
import json
import logging
from urllib.parse import urlparse, parse_qs, unquote

from .server_model import is_private_host

log = logging.getLogger(__name__)


def _b64_decode_padded(s):
    s = s.replace('-', '+').replace('_', '/')
    padded = s + '=' * (-len(s) % 4)
    return base64.b64decode(padded)


def _b64_decode_json(s):
    return json.loads(_b64_decode_padded(s))


def parse_link(raw_link, default_name="Server"):
    """Parse a vless:// or vmess:// link into a Server, or None."""
    if not raw_link:
        return None
    if raw_link.startswith('vless://'):
        return _parse_vless(raw_link, default_name)
    if raw_link.startswith('vmess://'):
        return _parse_vmess(raw_link, default_name)
    return None


def parse_links_from_text(text):
    """Extract all vless:// and vmess:// links from arbitrary text."""
    links = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(('vless://', 'vmess://')):
            links.append(line)
    return links


def _parse_vless(raw_link, default_name="Server"):
    """Parse vless://UUID@host:port?params#Name"""
    try:
        payload = raw_link[8:]
        fragment = ''
        if '#' in payload:
            payload, fragment = payload.rsplit('#', 1)
            fragment = unquote(fragment)
        name = fragment or default_name

        if '@' not in payload:
            return None
        uuid, rest = payload.split('@', 1)

        if '?' in rest:
            hostport, query_str = rest.split('?', 1)
        else:
            hostport, query_str = rest, ''

        if ':' not in hostport:
            return None
        host, port_str = hostport.rsplit(':', 1)
        port = int(port_str)

        params = parse_qs(query_str, keep_blank_values=True)
        def _param(key): return params.get(key, [''])[0]

        security = _param('security') or 'none'
        transport = _param('type') or 'tcp'
        flow = _param('flow')
        sni = _param('sni')
        fp = _param('fp') or 'chrome'
        pbk = _param('pbk')
        sid = _param('sid')
        enc = _param('encryption') or 'none'
        host_header = _param('host')
        path = _param('path') or _param('serviceName')

        if is_private_host(host):
            log.warning("VLESS link points to private/reserved IP: %s", host)

        from .server_model import Server, ProxyProtocol
        return Server(
            key=raw_link,
            name=name,
            host=host,
            port=port,
            protocol=ProxyProtocol.VLESS,
            uuid=uuid,
            security=security,
            transport=transport,
            flow=flow,
            encryption=enc,
            server_name=sni,
            fingerprint=fp,
            public_key=pbk,
            short_id=sid,
            path=path,
            host_header=host_header,
            is_private=is_private_host(host),
        )
    except (ValueError, IndexError) as e:
        log.debug("VLESS link parse failed: %s", e)
        return None


def _parse_vmess(raw_link, default_name="Server"):
    """Parse vmess://base64(JSON)"""
    try:
        payload = raw_link[8:]
        data = _b64_decode_json(payload)

        name = data.get('ps', '') or default_name
        host = data.get('add', '')
        port = int(data.get('port', 443))
        uuid = data.get('id', '')
        alter_id = int(data.get('aid', 0))
        vmess_sec = data.get('scy', 'auto')
        net = data.get('net', 'tcp')
        tls = data.get('tls', '')
        sni = data.get('sni', '')
        fp = data.get('fp', 'chrome')
        host_header = data.get('host', '')
        path = data.get('path', '')

        security = 'tls' if tls == 'tls' else 'none'

        if is_private_host(host):
            log.warning("VMess link points to private/reserved IP: %s", host)

        from .server_model import Server, ProxyProtocol
        return Server(
            key=raw_link,
            name=name,
            host=host,
            port=port,
            protocol=ProxyProtocol.VMESS,
            uuid=uuid,
            security=security,
            transport=net,
            encryption='auto',
            server_name=sni,
            fingerprint=fp,
            alter_id=alter_id,
            vmess_security=vmess_sec,
            path=path,
            host_header=host_header,
            is_private=is_private_host(host),
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        log.debug("VMess link parse failed: %s", e)
        return None
