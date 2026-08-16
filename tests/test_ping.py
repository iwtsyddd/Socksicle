"""Tests for utils.ping HTTP-over-SOCKS5 latency measurement."""
import socket
import threading
import time

from PySide6.QtCore import QThreadPool

from utils.ping import (
    direct_http_ping, direct_tcp_ping, http_ping_via_socks5_once,
    ping_via_socks5, tcp_connect_ping_via_socks5,
    PingJob, ProxyPingJob, PING_ERROR_SENTINEL,
)

CONNECT_OK = b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x50"
CONNECT_FAIL = b"\x05\x01"
HEADERS = b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\n"
NO_CONTENT = b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n"
BODY = b"pong"


class _Socks5TestServer:
    """Minimal SOCKS5 relay that sends an HTTP response in TCP segments."""

    def __init__(self, header_delay=0.0, data_delay=0.0, reject_connect=False,
                 drop_after_connect=False, silent=False, no_body=False,
                 truncate_headers=False):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.header_delay = header_delay
        self.data_delay = data_delay
        self.reject_connect = reject_connect
        self.drop_after_connect = drop_after_connect
        self.silent = silent
        self.no_body = no_body
        self.truncate_headers = truncate_headers
        self.method = None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                with conn:
                    conn.settimeout(10)
                    greeting = b""
                    while len(greeting) < 3:
                        chunk = conn.recv(4 - len(greeting))
                        if not chunk:
                            break
                        greeting += chunk
                    if greeting[:3] != b"\x05\x01\x00":
                        continue
                    conn.sendall(b"\x05\x00")
                    request = b""
                    while len(request) < 10:
                        chunk = conn.recv(64)
                        if not chunk:
                            break
                        request += chunk
                    if self.reject_connect:
                        conn.sendall(CONNECT_FAIL)
                        continue
                    conn.sendall(CONNECT_OK)
                    if self.drop_after_connect:
                        continue
                    http_request = b""
                    while b"\r\n\r\n" not in http_request:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        http_request += chunk
                    self.method = http_request.split(b" ", 1)[0]
                    if self.silent:
                        time.sleep(3)
                        continue
                    time.sleep(self.header_delay)
                    response = HEADERS if not self.no_body else NO_CONTENT
                    if self.truncate_headers:
                        conn.sendall(response[:24])
                        continue
                    conn.sendall(response)
                    time.sleep(self.data_delay)
                    if not self.no_body:
                        conn.sendall(BODY)
            except OSError:
                pass

    def close(self):
        self.sock.close()


class _RawListener:
    """Accepts one plain TCP connection and records the bytes received."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.data = None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return
        try:
            with conn:
                conn.settimeout(10)
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                self.data = data
        except OSError:
            pass

    def close(self):
        self.sock.close()


def test_ping_measures_until_headers_complete():
    srv = _Socks5TestServer(header_delay=0.2)
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=3)
        assert ms is not None
        assert ms >= 150
        assert ms < 2000
    finally:
        srv.close()


def test_ping_empty_204_response_is_a_success():
    srv = _Socks5TestServer(header_delay=0.1, no_body=True)
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=3)
        assert ms is not None
        assert ms >= 50
    finally:
        srv.close()


def test_ping_without_body_delay_still_returns_value():
    srv = _Socks5TestServer()
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=3)
        assert ms is not None
    finally:
        srv.close()


def test_ping_rejected_connect_returns_none():
    srv = _Socks5TestServer(reject_connect=True)
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=2)
        assert ms is None
    finally:
        srv.close()


def test_ping_closed_after_connect_returns_none():
    srv = _Socks5TestServer(drop_after_connect=True)
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=2)
        assert ms is None
    finally:
        srv.close()


def test_ping_timeout_returns_none():
    srv = _Socks5TestServer(silent=True)
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=0.3)
        assert ms is None
    finally:
        srv.close()


def test_ping_truncated_headers_returns_none():
    srv = _Socks5TestServer(truncate_headers=True)
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=2)
        assert ms is None
    finally:
        srv.close()


def test_ping_to_unreachable_proxy_returns_none():
    ms = http_ping_via_socks5_once("127.0.0.1", 1, timeout=0.5)
    assert ms is None


def test_direct_tcp_ping_measures_connect():
    srv = _Socks5TestServer()
    try:
        ms = direct_tcp_ping("127.0.0.1", srv.port, timeout=2)
        assert ms is not None
        assert ms >= 0
    finally:
        srv.close()


def test_direct_http_ping_tcp_connect_success():
    srv = _Socks5TestServer()
    try:
        ms = direct_http_ping("127.0.0.1", srv.port, timeout=3)
        assert ms is not None
        assert ms >= 0
    finally:
        srv.close()


def test_direct_http_ping_refused_returns_none():
    ms = direct_http_ping("127.0.0.1", 1, timeout=1)
    assert ms is None


def test_ping_get_sends_get_request():
    srv = _Socks5TestServer()
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=3)
        assert ms is not None
        assert srv.method == b"GET"
    finally:
        srv.close()


def test_ping_head_sends_head_request():
    srv = _Socks5TestServer(header_delay=0.1)
    try:
        ms = http_ping_via_socks5_once("127.0.0.1", srv.port, timeout=3,
                                       method="HEAD")
        assert srv.method == b"HEAD"
        assert ms is not None
        assert ms >= 50
    finally:
        srv.close()


def test_tcp_connect_ping_measures_connect():
    srv = _Socks5TestServer()
    try:
        ms = tcp_connect_ping_via_socks5("127.0.0.1", srv.port, timeout=2)
        assert ms is not None
        assert ms >= 0
    finally:
        srv.close()


def test_tcp_connect_ping_to_unreachable_proxy_returns_none():
    ms = tcp_connect_ping_via_socks5("127.0.0.1", 1, timeout=0.5)
    assert ms is None


def test_tcp_connect_ping_rejected_connect_returns_none():
    srv = _Socks5TestServer(reject_connect=True)
    try:
        ms = tcp_connect_ping_via_socks5("127.0.0.1", srv.port, timeout=2)
        assert ms is None
    finally:
        srv.close()


def test_ping_via_socks5_dispatches_tcp_connect():
    srv = _Socks5TestServer()
    try:
        ms = ping_via_socks5("127.0.0.1", srv.port, method="tcp_connect")
        assert ms is not None
        assert ms >= 0
    finally:
        srv.close()


def test_ping_via_socks5_default_is_http_get():
    srv = _Socks5TestServer()
    try:
        ms = ping_via_socks5("127.0.0.1", srv.port)
        assert ms is not None
        assert srv.method == b"GET"
    finally:
        srv.close()


def test_ping_via_socks5_unknown_method_falls_back_to_get():
    srv = _Socks5TestServer()
    try:
        ms = ping_via_socks5("127.0.0.1", srv.port, method="bogus")
        assert ms is not None
        assert srv.method == b"GET"
    finally:
        srv.close()


def test_proxy_ping_job_reports_real_latency(qapp):
    srv = _Socks5TestServer(header_delay=0.1)
    results = []
    pool = QThreadPool()
    try:
        pool.start(ProxyPingJob("127.0.0.1", srv.port, results.append))
        assert pool.waitForDone(6000)
        assert len(results) == 1
        assert results[0] is not None
        assert results[0] >= 50
    finally:
        srv.close()


def test_proxy_ping_job_failure_reports_none(qapp):
    srv = _Socks5TestServer(reject_connect=True)
    results = []
    pool = QThreadPool()
    try:
        pool.start(ProxyPingJob("127.0.0.1", srv.port, results.append))
        assert pool.waitForDone(6000)
        assert results == [None]
    finally:
        srv.close()


def test_ping_job_reports_ms(qapp):
    srv = _Socks5TestServer()
    results = []
    pool = QThreadPool()
    try:
        pool.start(PingJob(2, "127.0.0.1", srv.port,
                           lambda i, ms: results.append((i, ms)),
                           method="tcp_connect"))
        assert pool.waitForDone(6000)
        assert results and results[0][0] == 2
        assert results[0][1] >= 0
    finally:
        srv.close()


def test_ping_job_reports_error_sentinel_on_failure(qapp):
    results = []
    pool = QThreadPool()
    pool.start(PingJob(0, "127.0.0.1", 1,
                       lambda i, ms: results.append((i, ms)),
                       method="tcp_connect"))
    assert pool.waitForDone(6000)
    assert results == [(0, PING_ERROR_SENTINEL)]


def test_ping_job_http_get_goes_through_socks5(qapp):
    srv = _Socks5TestServer()
    results = []
    pool = QThreadPool()
    try:
        pool.start(PingJob(0, "127.0.0.1", 80, lambda i, ms: results.append((i, ms)),
                           method="http_get", socks5_port=srv.port))
        assert pool.waitForDone(6000)
        assert results and results[0][1] >= 0
        assert srv.method == b"GET"
    finally:
        srv.close()


def test_ping_job_http_head_goes_through_socks5(qapp):
    srv = _Socks5TestServer(header_delay=0.1)
    results = []
    pool = QThreadPool()
    try:
        pool.start(PingJob(0, "127.0.0.1", 80, lambda i, ms: results.append((i, ms)),
                           method="http_head", socks5_port=srv.port))
        assert pool.waitForDone(6000)
        assert results and results[0][1] is not PING_ERROR_SENTINEL
        assert srv.method == b"HEAD"
    finally:
        srv.close()


def test_ping_job_tcp_connect_is_direct(qapp):
    srv = _Socks5TestServer()
    results = []
    pool = QThreadPool()
    try:
        pool.start(PingJob(0, "127.0.0.1", srv.port,
                           lambda i, ms: results.append((i, ms)),
                           method="tcp_connect", socks5_port=1))
        assert pool.waitForDone(6000)
        assert results and results[0][1] >= 0
    finally:
        srv.close()


def test_ping_job_http_get_falls_back_to_direct_when_proxy_down(qapp):
    srv = _RawListener()
    results = []
    pool = QThreadPool()
    try:
        pool.start(PingJob(0, "127.0.0.1", srv.port,
                           lambda i, ms: results.append((i, ms)),
                           method="http_get", socks5_port=1))
        assert pool.waitForDone(6000)
        assert results and results[0][1] >= 0
        deadline = time.monotonic() + 2
        while srv.data is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert srv.data and srv.data.startswith(b"GET ")
    finally:
        srv.close()


def test_ping_job_http_get_unreachable_socks5_reports_sentinel(qapp):
    # socks5_port=1 means no proxy, so the job falls back to a direct
    # HTTP ping; 127.0.0.1:1 is also closed, so both the proxy and the
    # direct path fail deterministically and the sentinel is reported.
    results = []
    pool = QThreadPool()
    pool.start(PingJob(0, "127.0.0.1", 1, lambda i, ms: results.append((i, ms)),
                       method="http_get", socks5_port=1))
    assert pool.waitForDone(6000)
    assert results == [(0, PING_ERROR_SENTINEL)]


def test_direct_quic_ping_with_mock_udp_server():
    from utils.ping import direct_quic_ping
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("127.0.0.1", 0))
    port = udp_sock.getsockname()[1]

    def _mock_udp_responder():
        try:
            udp_sock.settimeout(2.0)
            data, addr = udp_sock.recvfrom(2048)
            # Reply with mock QUIC Version Negotiation packet
            udp_sock.sendto(b"\x80\x00\x00\x00\x00\x08" + b"\x00" * 8 + b"\x08" + b"\x00" * 8, addr)
        except Exception:
            pass
        finally:
            udp_sock.close()

    t = threading.Thread(target=_mock_udp_responder, daemon=True)
    t.start()

    ms = direct_quic_ping("127.0.0.1", port, timeout=1.0)
    assert ms is not None
    assert ms >= 0


def test_ping_job_hysteria2_uses_quic(qapp):
    from utils.ping import direct_quic_ping
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("127.0.0.1", 0))
    port = udp_sock.getsockname()[1]

    def _mock_udp_responder():
        try:
            udp_sock.settimeout(2.0)
            data, addr = udp_sock.recvfrom(2048)
            udp_sock.sendto(b"\x80\x00\x00\x00\x00\x08" + b"\x00" * 8 + b"\x08" + b"\x00" * 8, addr)
        except Exception:
            pass
        finally:
            udp_sock.close()

    t = threading.Thread(target=_mock_udp_responder, daemon=True)
    t.start()

    results = []
    pool = QThreadPool()
    pool.start(PingJob(0, "127.0.0.1", port, lambda i, ms: results.append((i, ms)),
                       protocol="hysteria2", socks5_port=1))
    assert pool.waitForDone(6000)
    assert results and results[0][1] >= 0