# Socksicle 🧦🧊


## Screenshot

<img width="35%" alt="Socksicle Screenshot" src="https://github.com/user-attachments/assets/11684261-97a0-4d4a-9da1-a42133a27be9" />

Socksicle is a multi-protocol proxy client for **Linux and Windows**, built with
PySide6 (Qt 6). It features a clean Material You (M3) inspired interface and a
pluggable engine backend that supports **Shadowsocks, VLESS, VMess, and Hysteria 2** through
`sslocal` (shadowsocks-rust), Xray-core, or sing-box.

## Features

- **Material You (M3) interface**: frameless rounded window, animated sliding pill tabs, animated toggles and cards, theme presets with light/dark-aware styling.
- **Multi-protocol support**: `ss://`, `vless://`, `vmess://`, `hysteria2://` and `hy2://` links, with a per-server protocol badge (e.g. `VLESS · Reality · WS`, `HY2`).
- **Global TUN Mode (Beta)**: routes all system traffic through a virtual network interface using `sing-box`, with secure non-root capabilities (`cap_net_admin`) via Polkit on Linux.
- **Kill Switch (Beta)**: OS firewall-level traffic blocking (`netsh advfirewall` on Windows, `nftables`/`iptables` on Linux) to prevent real IP leaks if the tunnel drops unexpectedly, complete with emergency startup cleanup and UAC elevation prompts.
- **Custom Secure DNS (DoH / DoT)**: configurable encrypted DNS resolvers including Cloudflare DoH (`1.1.1.1`), Quad9 DoH, AdGuard DoH (built-in ad/tracker blocking), Google DoH (`8.8.8.8`), and custom user-provided endpoints.
- **Auto-Healing Watchdog**: instant non-blocking auto-reconnection with retained UI state if an underlying proxy engine exits unexpectedly.
- **Engine selection**: choose between **sslocal**, **xray** or **sing-box** in Settings; missing engines are offered for **automatic download** (pinned official releases with speed and ETA progress) and can also be placed manually in `bin/`.
- **Subscription management**: Base64-encoded link lists, SIP008 JSON and plain-text subscriptions; `ss://`, `vless://`, `vmess://` and `hy2://` nodes are imported together with support for `Subscription-Userinfo`, `Profile-Title`, and auto-update intervals.
- **Traffic & expiry monitoring**: remaining data usage and expiration countdown badges (`⏳ 48h`, `⏳ 3d`, `[EXPIRED]`) dynamically computed from server expiration timestamps.
- **Subscription descriptions**: profile descriptions, node counts, last update time, and auto-update interval settings.
- **Ping methods**: HTTP GET, HTTP HEAD or TCP connect; "Ping All" measures latency across all nodes in parallel without freezing the UI.
- **Geo-location integration**: after connecting, public IP and country flags are fetched through the tunnel and rendered in the status card with bundled Windows Color Emoji support.
- **QR share & Encryption Studio**: every node exposes its link as a QR code; links and subscription URLs can also be encrypted into `tws3://` tokens with **TwinSock v3 URL Studio** (`gen_url.html`, with dedicated `.bat` and `.sh` launchers).
- **Export / import**: profiles (servers + subscriptions) can be exported to and imported from JSON files, honoring export-lock security flags.
- **Tray integration**: minimize to tray on close, per-server tray menu, Windows Explorer restart recovery, and auto-reconnect after sleep/hibernate resume.
- **User-local installation**: the Linux installer installs into `~/.local/share/socksicle` without root; Windows uses per-user `%APPDATA%` / `%LOCALAPPDATA%` locations.

## Requirements

- **Python 3.10+**
- **One proxy engine binary** (sslocal, xray or sing-box). None installed? The app offers to download one automatically on first launch.

## Installation

### Linux

Run the provided installer script — it installs the app into `~/.local/share/socksicle`, creates a `socksicle` launcher in `~/.local/bin` and a desktop entry in your application menu:

```bash
chmod +x install.sh
./install.sh
```

### Windows

1. Install Python 3.10+ (check "Add Python to PATH").
2. Install dependencies and run:

```bash
pip install .
socksicle          # or: python main.py
```

## Usage

1. Click **+ Add** and paste an `ss://`, `vless://`, `vmess://`, `hysteria2://` link, a subscription URL (`http(s)://`), or a `tws3://` share token.
2. Select a server in the list and flip the power switch. Connection is verified asynchronously in the background via local SOCKS5 probing on `127.0.0.1:<port>` (default `1080`).
3. Use **⚡ Ping All** to find the fastest node, **🔄 Update** to refresh a subscription, and the tray icon to connect/disconnect and quit.
4. The **Logs** panel shows live engine output; **About** links to the [GitHub repository](https://github.com/iwtsyddd/Socksicle).

## Settings

- **Proxy engine** — sslocal (Shadowsocks only), xray, or sing-box (automatically used in TUN mode).
- **TUN Mode (Beta)** — global system VPN routing via sing-box.
- **Kill Switch (Beta)** — OS firewall leak protection blocking direct outbound traffic on tunnel drops.
- **Secure DNS** — DoH / DoT presets (Cloudflare, Quad9, AdGuard, Google) or custom URL.
- **Local port** — the SOCKS5 listen port on `127.0.0.1`.
- **Auto-connect on startup** / **Minimize to tray on close** / **Auto-update subscriptions**.
- **Subscription User-Agent** — pick a client preset (clash, v2rayNG, hiddify, …) or default `socksicle`.
- **Ping method** — HTTP GET, HTTP HEAD, or TCP connect.
- **Fake X-hwid header** — optionally spoof the `X-hwid` header for panels.
- **TwinSock key** — personal AES-256-GCM key that signs and unlocks `tws3://` shares.

## Engines

| Engine | Protocols | Auto-download | Notes |
| ------ | --------- | ------------- | ----- |
| `sslocal` (shadowsocks-rust, pinned v1.24.0) | Shadowsocks | yes | Static musl builds on Linux; Windows x64 only |
| `xray` (Xray-core, pinned v25.4.3) | Shadowsocks, VLESS, VMess | yes | TLS / REALITY, ws / grpc / xhttp transports |
| `sing-box` (pinned v1.11.8) | Shadowsocks, VLESS, VMess, Hysteria 2 | yes | TLS / REALITY, ws / grpc / http transports, TUN mode, Obfs |

Engine binaries are located in, in order: `bin/` next to the app, the per-user config `bin/` directory, `bin/<engine>/` subdirectories, and finally the system `PATH`. Downloads are validated (executable format + `--version`) before being installed atomically.

## Configuration & Storage

All settings, servers and subscriptions are stored under the per-user config directory, no admin rights needed:

- **Linux**: `~/.config/socksicle/`
- **Windows**: `%APPDATA%\socksicle\` (logs in `%LOCALAPPDATA%\socksicle\logs`)

Files: `servers.json`, `subscriptions.json`, `settings.json`, `drawer.json` (TwinSock vault), and `bin/` with app-managed engine binaries.

> **TwinSock v3 vault note**: passwords, keys, UUIDs and subscription URLs are stored as `tws3.` tokens encrypted with an **AES-256-GCM AEAD** key bound to this machine's stable hardware fingerprint (Windows `MachineGuid` / Linux `machine-id`). Copying the config to another machine will not unlock it. `gen_url.html` (and the `URL Encryption Studio.bat` / `.sh` launchers) provides a modern 2026 client-side zero-knowledge tool for generating `tws3://` tokens offline with built-in QR code generation; the same generator is hosted online at <https://iwtsyddd.github.io/TwinSockGen/>.

## Testing

The pytest suite runs headless (`QT_QPA_PLATFORM=offscreen`) and never
touches the network or real subprocesses:

```bash
python -m pytest tests -q
```

CI (GitHub Actions) runs the same suite on every push and pull request.

## License

MIT — see the [LICENSE](LICENSE) file.
