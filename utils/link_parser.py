"""Parse vless://, vmess://, hysteria2:// and hy2:// links into Server objects."""
import base64
import json
import logging
import re
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
    """Parse a vless://, vmess://, hysteria2://, or hy2:// link into a Server, or None."""
    if not raw_link:
        return None
    if raw_link.startswith('vless://'):
        return _parse_vless(raw_link, default_name)
    if raw_link.startswith('vmess://'):
        return _parse_vmess(raw_link, default_name)
    if raw_link.startswith(('hysteria2://', 'hy2://')):
        return _parse_hysteria2(raw_link, default_name)
    return None


def parse_links_from_text(text):
    """Extract all supported proxy links from arbitrary text."""
    links = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(('vless://', 'vmess://', 'hysteria2://', 'hy2://', 'ss://')):
            links.append(line)
    return links


def _parse_mbps(val: str) -> int:
    """Parse bandwidth string into integer Mbps."""
    if not val:
        return 0
    cleaned = re.sub(r'(?i)(mbps|mb/s|m|kbps|k).*', '', val).strip()
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return 0


def _parse_hysteria2(raw_link, default_name="Server"):
    """Parse hysteria2://[auth@]host[:port]?params#Name or hy2://..."""
    try:
        if raw_link.startswith('hysteria2://'):
            payload = raw_link[12:]
        elif raw_link.startswith('hy2://'):
            payload = raw_link[6:]
        else:
            return None

        fragment = ''
        if '#' in payload:
            payload, fragment = payload.rsplit('#', 1)
            fragment = unquote(fragment)
        name = fragment or default_name

        if '@' in payload:
            auth_str, rest = payload.split('@', 1)
            password = unquote(auth_str)
        else:
            password = ""
            rest = payload

        if '?' in rest:
            hostport, query_str = rest.split('?', 1)
        else:
            hostport, query_str = rest, ''

        if not hostport:
            return None

        # Parse host and port (support IPv6 [::1]:443 and [::1])
        if hostport.startswith('[') and ']' in hostport:
            host_part, _, port_part = hostport.partition(']')
            host = host_part[1:]
            if port_part.startswith(':'):
                port = int(port_part[1:])
            else:
                port = 443
        elif ':' in hostport:
            host, port_str = hostport.rsplit(':', 1)
            port = int(port_str)
        else:
            host = hostport
            port = 443

        if not host:
            return None

        params = parse_qs(query_str, keep_blank_values=True)
        def _param(key): return params.get(key, [''])[0]

        sni = _param('sni') or _param('peer')
        insecure_param = (
            _param('insecure') or _param('allowInsecure') or _param('allow_insecure') or
            _param('skip-cert-verify') or _param('skip_cert_verify') or _param('tls_insecure')
        )
        if insecure_param:
            insecure = insecure_param.lower() not in ('0', 'false', 'no', 'off')
        else:
            insecure = True
        obfs = _param('obfs')
        obfs_password = _param('obfs-password') or _param('obfs_password')
        ports = _param('mport') or _param('ports') or _param('port')
        up_str = _param('up') or _param('upmbps') or _param('up_mbps')
        down_str = _param('down') or _param('downmbps') or _param('down_mbps')

        if is_private_host(host):
            log.warning("Hysteria2 link points to private/reserved IP: %s", host)

        from .server_model import Server, ProxyProtocol
        return Server(
            key=raw_link,
            name=name,
            host=host,
            port=port,
            protocol=ProxyProtocol.HYSTERIA2,
            password=password,
            server_name=sni,
            insecure=insecure,
            obfs=obfs,
            obfs_password=obfs_password,
            ports=ports,
            up_mbps=_parse_mbps(up_str),
            down_mbps=_parse_mbps(down_str),
            is_private=is_private_host(host),
        )
    except (ValueError, IndexError) as e:
        log.debug("Hysteria2 link parse failed: %s", e)
        return None


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
