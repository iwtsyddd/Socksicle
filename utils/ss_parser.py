import base64
from urllib.parse import urlparse, unquote, parse_qs

def decode_ss_link(ss_link):
    if not ss_link.startswith('ss://'):
        return None

    ss_link = ss_link[5:]

    tag = ''
    if '#' in ss_link:
        ss_link, tag = ss_link.split('#', 1)
        tag = unquote(tag)

    try:
        decoded = base64.urlsafe_b64decode(ss_link + '=' * (-len(ss_link) % 4)).decode()
        method, rest = decoded.split(':', 1)
        password, server_port = rest.rsplit('@', 1)
        server, port = server_port.split(':', 1)
        return {
            'server': server,
            'port': int(port),
            'method': method,
            'password': password,
            'tag': tag
        }
    except Exception:
        pass

    try:
        parsed = urlparse('ss://' + ss_link)
        base64_part = parsed.username
        server = parsed.hostname
        port = parsed.port

        decoded = base64.urlsafe_b64decode(base64_part + '=' * (-len(base64_part) % 4)).decode()
        method, password = decoded.split(':', 1)

        return {
            'server': server,
            'port': int(port),
            'method': method,
            'password': password,
            'tag': tag
        }
    except Exception:
        return None
