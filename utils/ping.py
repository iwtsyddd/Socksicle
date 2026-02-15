import socks
import socket
import time

def http_ping_via_socks5_once(host, socks5_port, timeout=3):
    """Ping via SOCKS5 proxy (for active connection)."""
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, "127.0.0.1", socks5_port)
    s.settimeout(timeout)
    try:
        start = time.time()
        s.connect((host, 80))
        s.close()
        return (time.time() - start) * 1000
    except Exception:
        s.close()
        return None

def direct_tcp_ping(host, port, timeout=2):
    """Direct TCP ping to server IP/Port (for list pinging)."""
    try:
        start = time.time()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, int(port)))
        sock.close()
        return (time.time() - start) * 1000
    except Exception:
        return None
