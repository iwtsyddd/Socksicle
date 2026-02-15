import urllib.request
import base64
import json
import os

def parse_subscription(url):
    """Fetch and parse shadowsocks subscription (Base64)."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            content = response.read().decode('utf-8').strip()
            
            # Extract traffic info from headers
            info_header = response.headers.get('Subscription-Userinfo')
            traffic_info = None
            if info_header:
                # Format: upload=X; download=Y; total=Z; expire=T
                parts = dict(item.split('=') for item in info_header.replace(' ', '').split(';') if '=' in item)
                traffic_info = {
                    'used': int(parts.get('upload', 0)) + int(parts.get('download', 0)),
                    'total': int(parts.get('total', 0)),
                    'expire': int(parts.get('expire', 0))
                }

            # Decode Base64 content
            try:
                decoded_content = base64.b64decode(content + '=' * (-len(content) % 4)).decode('utf-8')
            except:
                decoded_content = content # Not base64 encoded
            
            links = decoded_content.splitlines()
            # Filter only ss:// links
            ss_links = [link for link in links if link.startswith('ss://')]
            
            return ss_links, traffic_info
    except Exception as e:
        print(f"Subscription error: {e}")
        return [], None

def save_subscriptions(subs):
    path = os.path.expanduser("~/.config/socksicle/subscriptions.json")
    with open(path, 'w') as f:
        json.dump(subs, f)

def load_subscriptions():
    path = os.path.expanduser("~/.config/socksicle/subscriptions.json")
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return []
