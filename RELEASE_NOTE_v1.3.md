# Socksicle 1.3

🌐 Windows
Windows: Socksicle now feels right at home on Windows — native installer, high-DPI scaling, taskbar grouping via `AppUserModelID`, a tray icon that survives Explorer restarts, and automatic proxy re-connect after sleep/hibernate resume.

⚙️ Engines
Engines: pick sslocal, xray-core or sing-box in Settings — missing engines are auto-downloaded from pinned official releases, with a progress dialog showing speed and ETA; crashed engines are cleaned up so local ports are never held by zombies.

🗄️ Vault
TwinSock v2 vault: passwords, UUIDs, keys and subscription URLs are now encrypted at rest with a key bound to your machine's fingerprint — configs are useless on other machines, foreign configs are detected and retired, and legacy configs migrate automatically.
Sharing: any server or subscription can be shared as an encrypted `tws2://` token signed with your personal key — paste it on another device and it unlocks there.

📢 Subscription
Descriptions: profile title, description and update info now appear right in the traffic card — including `base64:`-encoded headers and descriptions taken from the body preamble.
Formats: SIP008 JSON subscriptions join the Base64 link lists — `ss://`, `vless://` and `vmess://` nodes all import together.
Safety & refresh: only `http(s)` URLs are accepted, and targets resolving to private/loopback IPs are rejected — plus per-subscription auto-update honoring the provider's refresh interval, User-Agent presets and a fake `X-hwid` header for panels that filter by client.

⚡ Ping
Ping methods: HTTP GET, HTTP HEAD or TCP connect, selectable in Settings — "Ping All" measures every server in the tab with your chosen method, through the local SOCKS5 proxy when it's up.
Honest status: "Connected" now appears only after the local proxy answers a real SOCKS5 handshake probe — no more forced status after a fixed timeout.

🏷️ Protocols
VLESS & VMess: full support including TLS/Reality and WS/gRPC/XHTTP transports, with protocol badges in the server list — and every node stays shareable via QR code or an encrypted `tws2://` token.