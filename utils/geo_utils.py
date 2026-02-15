import json
import urllib.request
import socks
from PySide6.QtGui import QImage

def get_flag_emoji(country_code):
    if not country_code or len(country_code) != 2:
        return "🌐"
    return chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)

class SOCKS5Handler(urllib.request.BaseHandler):
    def __init__(self, port):
        self.port = port
    def http_open(self, req):
        def make_socks_conn(*args, **kwargs):
            s = socks.socksocket()
            s.set_proxy(socks.SOCKS5, "127.0.0.1", int(self.port))
            s.connect(args[0])
            return s
        # This is a bit of a hack for urllib, but safer than global patch
        import http.client
        class SOCKSConnection(http.client.HTTPConnection):
            def connect(self):
                self.sock = make_socks_conn((self.host, self.port))
        
        return self.do_open(SOCKSConnection, req)

def fetch_ip_info_via_proxy(proxy_port):
    """Fetch public IP info through SOCKS5 proxy."""
    url = "http://ip-api.com/json/?fields=status,countryCode,query"
    print(f"[GeoIP] Fetching IP via proxy on port {proxy_port}...", flush=True)
    
    try:
        opener = urllib.request.build_opener(SOCKS5Handler(proxy_port))
        with opener.open(url, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                print(f"[GeoIP] Success: {data.get('query')}", flush=True)
                return {
                    "ip": data.get("query"),
                    "flag": get_flag_emoji(data.get("countryCode"))
                }
    except Exception as e:
        print(f"[GeoIP] Failed: {e}", flush=True)
    return None
