import json
import urllib.request
import socks
from PySide6.QtGui import QImage

def get_flag_emoji(country_code):
    if not country_code or len(country_code) != 2:
        return "🌐"
    return chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)

def fetch_ip_info_via_proxy(proxy_port):
    """Fetch public IP info through SOCKS5 proxy using socksocket directly."""
    url_host = "ip-api.com"
    url_path = "/json/?fields=status,countryCode,query"
    print(f"[GeoIP] Fetching IP via proxy on port {proxy_port}...", flush=True)
    
    s = socks.socksocket()
    try:
        s.set_proxy(socks.SOCKS5, "127.0.0.1", int(proxy_port))
        s.settimeout(10)
        s.connect((url_host, 80))
        
        request = f"GET {url_path} HTTP/1.1\r\nHost: {url_host}\r\nConnection: close\r\n\r\n"
        s.sendall(request.encode())
        
        response = b""
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            response += chunk
        
        # Simple HTTP response parsing
        header_end = response.find(b"\r\n\r\n")
        if header_end != -1:
            body = response[header_end+4:].decode('utf-8')
            data = json.loads(body)
            if data.get("status") == "success":
                print(f"[GeoIP] Success: {data.get('query')}", flush=True)
                return {
                    "ip": data.get("query"),
                    "flag": get_flag_emoji(data.get("countryCode"))
                }
    except Exception as e:
        print(f"[GeoIP] Failed: {e}", flush=True)
    finally:
        s.close()
    return None
