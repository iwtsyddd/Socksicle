import socks
import socket
import time

def http_ping_via_socks5_once(host, socks5_port, timeout=3):
    s = socks.socksocket()
    s.set_proxy(socks.SOCKS5, "127.0.0.1", socks5_port)
    s.settimeout(timeout)
    try:
        start = time.time()
        s.connect((host, 80))
        http_request = b"GET / HTTP/1.1\r\nHost: " + host.encode() + b"\r\nConnection: close\r\n\r\n"
        s.sendall(http_request)
        s.recv(1024)
        end = time.time()
        s.close()
        return (end - start) * 1000
    except Exception:
        s.close()
        return None
