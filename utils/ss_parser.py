import base64
from urllib.parse import unquote


def decode_ss_link(ss_link):
    if not ss_link.startswith('ss://'):
        return None

    ss_link = ss_link[5:]
    if '#' in ss_link:
        ss_link, tag = ss_link.split('#', 1)
        tag = unquote(tag)
    else:
        tag = ''

    try:
        decoded = base64.urlsafe_b64decode(ss_link + '=' * (-len(ss_link) % 4)).decode()
        method, password_server = decoded.split(':', 1)
        password, server_port = password_server.rsplit('@', 1)
        server, port = server_port.split(':', 1)
    except Exception:
        return None

    return {
        'server': server,
        'port': int(port),
        'method': method,
        'password': password,
        'tag': tag
    }