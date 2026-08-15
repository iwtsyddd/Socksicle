import json
import logging
import socks
from PySide6.QtGui import QImage

log = logging.getLogger("geo_utils")

MAX_RESPONSE_BYTES = 64 * 1024
MAX_HEADER_BYTES = 16 * 1024
_RESET_WINERRNOS = {10052, 10053, 10054, 10058}


def get_flag_emoji(country_code):
    if not country_code or len(country_code) != 2:
        return "🌐"
    return chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)


def _recv_until(sock, delimiter, limit):
    data = b""
    while delimiter not in data:
        remaining = limit - len(data)
        if remaining <= 0:
            return data
        chunk = sock.recv(min(4096, remaining))
        if not chunk:
            return None
        data += chunk
    return data


def _recv_line(sock, buffered, limit):
    buf = buffered
    while b"\r\n" not in buf:
        if len(buf) >= limit:
            return None, buf
        chunk = sock.recv(4096)
        if not chunk:
            return None, buf
        buf += chunk
    line, buf = buf.split(b"\r\n", 1)
    return line, buf


def _recv_exact(sock, buffered, count):
    buf = buffered
    while len(buf) < count:
        chunk = sock.recv(4096)
        if not chunk:
            return None, buf
        buf += chunk
    return buf[:count], buf[count:]


def _drain_trailers(sock, buffered):
    buf = buffered
    while b"\r\n\r\n" not in buf:
        if len(buf) > MAX_HEADER_BYTES:
            return buf
        chunk = sock.recv(4096)
        if not chunk:
            return buf
        buf += chunk
    return buf


def _read_chunked_body(sock, buffered):
    body = b""
    buf = buffered
    while True:
        size_line, buf = _recv_line(sock, buf, 4096)
        if size_line is None:
            log.warning("HTTP response: truncated chunked body (missing terminal 0-chunk)")
            return None
        try:
            size = int(size_line.split(b";", 1)[0].strip(), 16)
        except ValueError:
            log.warning("HTTP response: malformed chunk size line %r",
                        size_line.decode("latin-1", "replace"))
            return None
        if size < 0 or len(body) + size > MAX_RESPONSE_BYTES:
            log.warning("HTTP response: chunked body exceeds limit (%d bytes)",
                        MAX_RESPONSE_BYTES)
            return None
        chunk, buf = _recv_exact(sock, buf, size)
        if chunk is None:
            log.warning("HTTP response: truncated chunked body (chunk of %d bytes not fully received)",
                        size)
            return None
        body += chunk
        if size == 0:
            _drain_trailers(sock, buf)
            return body
        crlf, buf = _recv_exact(sock, buf, 2)
        if crlf != b"\r\n":
            log.warning("HTTP response: malformed chunk terminator")
            return None


def _read_http_response(sock, timeout=10):
    """Read an HTTP response body following RFC framing.

    Supports Content-Length, Transfer-Encoding: chunked, and
    close-delimited bodies. Returns the raw body bytes on success,
    or None with a logged concrete reason when the response is
    malformed, carries a non-200 status, or has an empty/oversized body.
    """
    sock.settimeout(timeout)
    data = _recv_until(sock, b"\r\n\r\n", MAX_HEADER_BYTES)
    if data is None:
        log.warning("HTTP response: connection closed before end of headers")
        return None
    if b"\r\n\r\n" not in data:
        log.warning("HTTP response: headers exceed %d bytes without terminator",
                    MAX_HEADER_BYTES)
        return None
    header_block, rest = data.split(b"\r\n\r\n", 1)
    lines = header_block.split(b"\r\n")
    status_parts = lines[0].split(b" ", 2)
    if len(status_parts) < 2 or status_parts[1] != b"200":
        status = (status_parts[1].decode("latin-1", "replace")
                  if len(status_parts) >= 2 else "<malformed>")
        log.warning("HTTP response: unexpected status %s", status)
        return None
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(b":")
        if sep:
            headers[name.strip().lower()] = value.strip()

    transfer_encoding = headers.get(b"transfer-encoding", b"").lower()
    if b"chunked" in transfer_encoding:
        body = _read_chunked_body(sock, rest)
        return body if body is not None else None

    content_length = headers.get(b"content-length")
    if content_length is not None:
        try:
            clen = int(content_length)
        except ValueError:
            log.warning("HTTP response: invalid Content-Length %r",
                        content_length.decode("latin-1", "replace"))
            return None
        if clen <= 0:
            log.warning("HTTP response: empty body (Content-Length: %d)", clen)
            return None
        if clen > MAX_RESPONSE_BYTES:
            log.warning("HTTP response: Content-Length %d exceeds limit (%d bytes)",
                        clen, MAX_RESPONSE_BYTES)
            return None
        body = rest
        while len(body) < clen:
            chunk = sock.recv(4096)
            if not chunk:
                log.warning("HTTP response: short body (got %d of %d bytes)",
                            len(body), clen)
                return None
            body += chunk
        return body[:clen]

    body = rest
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            log.warning("HTTP response: body exceeds limit (%d bytes) without framing",
                        MAX_RESPONSE_BYTES)
            return None
    if not body:
        log.warning("HTTP response: empty body without framing")
        return None
    return body


def fetch_ip_info_via_proxy(proxy_port, timeout=10):
    """Fetch public IP info through SOCKS5 proxy using socksocket directly."""
    url_host = "ip-api.com"
    url_path = "/json/?fields=status,countryCode,query"
    log.info("Fetching IP via proxy on port %s...", proxy_port)

    s = socks.socksocket()
    try:
        s.set_proxy(socks.SOCKS5, "127.0.0.1", int(proxy_port))
        s.settimeout(timeout)
        s.connect((url_host, 80))

        request = (
            f"GET {url_path} HTTP/1.1\r\n"
            f"Host: {url_host}\r\n"
            f"User-Agent: Socksicle/1.1 (geo)\r\n"
            "Connection: close\r\n\r\n"
        )
        s.sendall(request.encode())

        body = _read_http_response(s, timeout)
        if body is None:
            return None

        data = json.loads(body.decode("utf-8"))
        if data.get("status") == "success":
            log.info("Success: %s", data.get('query'))
            return {
                "ip": data.get("query"),
                "flag": get_flag_emoji(data.get("countryCode"))
            }
        log.debug("Geo lookup returned status %r", data.get("status"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        if isinstance(e, OSError) and getattr(e, "winerror", None) in _RESET_WINERRNOS:
            log.debug("Failed (tunnel torn down): %s", e)
        else:
            log.warning("Failed: %s", e)
    finally:
        s.close()
    return None