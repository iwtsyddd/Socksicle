import logging
import socket
import time
import socks
from PySide6.QtCore import QRunnable

log = logging.getLogger(__name__)

# Value reported to the UI when a ping failed; kept distinct from any
# real latency since ms values are always >= 0.
PING_ERROR_SENTINEL = -1.0

# Probe endpoint resolved through the tunnel. It answers with
# HTTP 204 No Content, i.e. the response carries no body at all,
# so header completion is the earliest reliable success signal.
PING_PROBE_HOST = "connectivitycheck.gstatic.com"
PING_PROBE_PATH = "/generate_204"
PING_PROBE_PORT = 80

PING_METHODS = ("http_get", "http_head", "tcp_connect")
DEFAULT_PING_METHOD = "http_get"
PING_TIMEOUTS = {"http_get": 3.0, "http_head": 3.0, "tcp_connect": 2.0}

def http_ping_via_socks5_once(host, socks5_port, timeout=3, method="GET"):
    """Measure round-trip latency through a local SOCKS5 proxy.

    Sends a minimal HTTP GET or HEAD through the proxy and times the
    interval until the response headers complete. The probe endpoint
    replies with an empty 204 body, so waiting for a body byte would
    never succeed; the local SOCKS5 handshake alone is not a meaningful
    latency signal either.
    """
    method = "GET" if method.upper() not in ("GET", "HEAD") else method.upper()
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, "127.0.0.1", socks5_port)
    s.settimeout(timeout)
    try:
        start = time.monotonic()
        s.connect((host, PING_PROBE_PORT))
        s.sendall(
            (method + " " + PING_PROBE_PATH).encode("ascii") + b" HTTP/1.1\r\n"
            b"Host: " + PING_PROBE_HOST.encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n")
        buffer = b""
        for _ in range(64):
            chunk = s.recv(1024)
            if not chunk:
                break
            buffer += chunk
            if buffer.startswith(b"HTTP/") and b"\r\n\r\n" in buffer:
                return (time.monotonic() - start) * 1000
        return None
    except (socket.error, OSError, socks.SOCKS5Error, TimeoutError) as e:
        log.debug("SOCKS5 ping to %s failed: %s", host, e)
        return None
    except Exception as e:
        log.debug("SOCKS5 ping to %s unexpected failure: %s", host, e)
        return None
    finally:
        s.close()


def tcp_connect_ping_via_socks5(host, socks5_port, timeout=2):
    """Measure latency until the SOCKS5 CONNECT reply (one remote RTT)."""
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, "127.0.0.1", socks5_port)
    s.settimeout(timeout)
    try:
        start = time.monotonic()
        s.connect((host, PING_PROBE_PORT))
        return (time.monotonic() - start) * 1000
    except (socket.error, OSError, socks.SOCKS5Error, TimeoutError) as e:
        log.debug("SOCKS5 TCP ping to %s failed: %s", host, e)
        return None
    except Exception as e:
        log.debug("SOCKS5 TCP ping to %s unexpected failure: %s", host, e)
        return None
    finally:
        s.close()


def ping_via_socks5(host, socks5_port, method=DEFAULT_PING_METHOD, timeout=None):
    """Dispatch active-ping by method: http_get | http_head | tcp_connect."""
    if method not in PING_METHODS:
        method = DEFAULT_PING_METHOD
    if timeout is None:
        timeout = PING_TIMEOUTS[method]
    if method == "tcp_connect":
        return tcp_connect_ping_via_socks5(host, socks5_port, timeout)
    return http_ping_via_socks5_once(
        host, socks5_port, timeout=timeout,
        method="HEAD" if method == "http_head" else "GET")


def socks5_proxy_ready(port, timeout=0.5):
    """Verify a local SOCKS5 proxy accepts a handshake (lightweight probe)."""
    try:
        s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
        with s:
            s.sendall(b"\x05\x01\x00")
            return s.recv(2) == b"\x05\x00"
    except (socket.error, OSError, ConnectionRefusedError, TimeoutError) as e:
        log.debug("SOCKS5 proxy probe on port %s failed: %s", port, e)
        return False

def direct_tcp_ping(host, port, timeout=2):
    """Direct TCP ping to server IP/Port (for list pinging)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        start = time.monotonic()
        sock.connect((host, int(port)))
        return (time.monotonic() - start) * 1000
    except (socket.error, OSError, ConnectionRefusedError, TimeoutError) as e:
        log.debug("Direct TCP ping to %s:%s failed: %s", host, port, e)
        return None
    finally:
        sock.close()


def direct_http_ping(host, port, timeout=3, method="GET"):
    """Direct HTTP GET/HEAD to the server's real host:port.

    Success signal is the completed TCP connect (like direct_tcp_ping);
    an HTTP response is optional because proxy servers usually do not
    serve HTTP on their inbound port. If response headers arrive, the
    measurement is taken at header completion.
    """
    method = "GET" if method.upper() not in ("GET", "HEAD") else method.upper()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        try:
            start = time.monotonic()
            sock.connect((host, int(port)))
        except (socket.error, OSError, ConnectionRefusedError,
                TimeoutError) as e:
            log.debug("Direct HTTP ping to %s:%s failed: %s", host, port, e)
            return None
        except Exception as e:
            log.debug("Direct HTTP ping to %s:%s unexpected failure: %s",
                      host, port, e)
            return None
        try:
            sock.sendall(
                (method + " /generate_204 HTTP/1.1\r\n").encode("ascii")
                + b"Host: " + host.encode("ascii")
                + b"\r\nConnection: close\r\n\r\n")
            buffer = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                buffer += chunk
                if b"\r\n\r\n" in buffer:
                    return (time.monotonic() - start) * 1000
        except Exception:
            # TCP connect is the success signal; a missing or failed HTTP
            # exchange (server not speaking HTTP, recv timeout) still counts.
            pass
        return (time.monotonic() - start) * 1000
    finally:
        sock.close()


class PingJob(QRunnable):
    """Ping one server off the GUI thread via the global thread pool.

    Dispatches by method: tcp_connect = direct TCP to the server,
    http_get/http_head = HTTP through the local SOCKS5 proxy when it
    is running, otherwise a direct HTTP ping to the server.
    """

    def __init__(self, index, host, port, callback,
                 method=DEFAULT_PING_METHOD, socks5_port=None):
        super().__init__()
        self.index = index
        self.host = host
        self.port = port
        self.callback = callback
        self.method = method
        self.socks5_port = socks5_port

    def run(self):
        try:
            if self.method == "tcp_connect":
                ms = direct_tcp_ping(self.host, self.port)
            elif self.socks5_port is not None and socks5_proxy_ready(
                    self.socks5_port, timeout=0.5):
                ms = http_ping_via_socks5_once(
                    self.host, self.socks5_port,
                    timeout=PING_TIMEOUTS.get(self.method, 3.0),
                    method="HEAD" if self.method == "http_head" else "GET")
            else:
                ms = direct_http_ping(
                    self.host, self.port,
                    timeout=PING_TIMEOUTS.get(self.method, 3.0),
                    method="HEAD" if self.method == "http_head" else "GET")
        except Exception as e:
            log.debug("Ping to %s:%s raised: %s", self.host, self.port, e)
            ms = None
        self.callback(self.index,
                      ms if ms is not None else PING_ERROR_SENTINEL)


class ProxyPingJob(QRunnable):
    """Ping the active connection through its local SOCKS5 proxy off the GUI thread."""

    def __init__(self, host, port, callback, method=DEFAULT_PING_METHOD):
        super().__init__()
        self.host = host
        self.port = port
        self.callback = callback
        self.method = method

    def run(self):
        try:
            ms = ping_via_socks5(self.host, self.port, self.method)
        except Exception as e:
            log.debug("Proxy ping on port %s raised: %s", self.port, e)
            ms = None
        self.callback(ms)