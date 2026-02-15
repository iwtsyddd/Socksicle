import json
import urllib.request
import socket

def get_flag_emoji(country_code):
    """Convert ISO country code to flag emoji."""
    if not country_code or len(country_code) != 2:
        return "🌐"
    # Offset to convert regional indicator symbols
    return chr(ord(country_code[0].upper()) + 127397) + chr(ord(country_code[1].upper()) + 127397)

def fetch_geo_info(host):
    """Fetch country code and city for a given host or IP."""
    try:
        # Resolve hostname to IP if necessary
        ip = socket.gethostbyname(host)
        url = f"http://ip-api.com/json/{ip}?fields=status,countryCode,city"
        with urllib.request.urlopen(url, timeout=3) as response:
            data = json.loads(response.read().decode())
            if data.get("status") == "success":
                return {
                    "country_code": data.get("countryCode"),
                    "city": data.get("city"),
                    "ip": ip,
                    "flag": get_flag_emoji(data.get("countryCode"))
                }
    except Exception:
        pass
    return None
