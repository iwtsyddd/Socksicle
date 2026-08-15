# Socksicle 🧦🧊

Socksicle is a multi-protocol proxy client for **Linux and Windows**, built with
PySide6 (Qt 6). It features a clean Material Design 3 inspired interface and a
pluggable engine backend that supports **Shadowsocks, VLESS and VMess** through
`sslocal` (shadowsocks-rust), Xray-core, or sing-box.

## Features

- **Material Design 3 interface**: frameless rounded window, animated toggles
  and cards, light/dark-aware styling.
- **Multi-protocol support**: `ss://`, `vless://` and `vmess://` links, with a
  per-server protocol badge (e.g. `VLESS · Reality · WS`).
- **Engine selection**: choose between **sslocal**, **xray** or **sing-box**
  in Settings; missing engines are offered for **automatic download**
  (pinned official releases, with a progress dialog showing speed and ETA)
  and can also be placed manually in `bin/` next to the app.
- **Subscription management**: Base64-encoded link lists, SIP008 JSON and
  plain-text subscriptions; `ss://`, `vless://` and `vmess://` nodes are
  imported together. Extended headers (`Subscription-Userinfo`,
  `Profile-Title`, `Profile-Description`, `Profile-Update-Interval`, …) are
  honored, including `base64:`-encoded values.
- **Traffic & expiry monitoring**: remaining data usage and expiration date
  are shown as a progress bar when the provider sends `Subscription-Userinfo`
  or SIP008 usage data.
- **Subscription descriptions**: the panel description (header or body
  preamble) is displayed with profile title, node count, last-update date and
  the auto-update interval.
- **Auto-update subscriptions**: on startup and periodically (respecting the
  provider's update interval), plus a manual "Update" button per subscription.
- **Ping methods**: HTTP GET, HTTP HEAD or TCP connect, selectable in
  Settings; "Ping All" measures every server in the current tab in parallel
  through the local SOCKS5 proxy (or directly to the server).
- **Geo-location integration**: after connecting, the public IP and country
  flag are fetched through the tunnel (via `ip-api.com`) and shown in the
  status card.
- **QR share**: every server exposes its link as a QR code; server links or
  subscription URLs can also be shared as encrypted `tws2://` tokens.
- **Export / import**: profiles (servers + subscriptions) can be exported to
  and imported from a JSON file.
- **Tray integration**: minimize to tray on close, per-server tray menu, and
  on Windows the tray re-registers after Explorer restarts and the proxy
  **auto-reconnects after sleep/hibernate**.
- **User-local installation**: the Linux installer installs into the home
  directory without root; Windows uses per-user `%APPDATA%` / `%LOCALAPPDATA%`
  locations.

## Requirements

- **Python 3.10+**
- **One proxy engine binary** (sslocal, xray or sing-box). None installed?
  The app offers to download one automatically on first launch.

## Installation

### Linux

Run the provided installer script — it installs the app into
`~/.local/share/socksicle`, creates a `socksicle` launcher in
`~/.local/bin` and a desktop entry in your application menu:

```bash
chmod +x install.sh
./install.sh
```

### Windows

1. Install Python 3.10+ (check "Add Python to PATH").
2. Run `install_win.bat` — it installs the Python dependencies via
   `pip install .` and reports which proxy engines are missing.

Alternatively, on any platform:

```bash
pip install .
socksicle          # or: python main.py
```

## Usage

1. Click **+ Add** and paste an `ss://`, `vless://`, `vmess://` link, a
   subscription URL (`http(s)://`), or a `tws2://` share token.
2. Select a server in the list and flip the power switch. Connection is
   verified by probing the local SOCKS5 proxy on `127.0.0.1:<port>`
   (default `1080`).
3. Use **⚡ Ping All** to find the fastest node, **🔄 Update** to refresh a
   subscription, and the tray icon to connect/disconnect and quit.
4. The **Logs** panel shows live engine output; **About** links to the
   [GitHub repository](https://github.com/iwtsyddd/Socksicle).

## Settings

- **Proxy engine** — sslocal (Shadowsocks only), xray, or sing-box; switching
  engines disconnects an active connection first.
- **Local port** — the SOCKS5 listen port on `127.0.0.1` (takes effect on the
  next connect while connected).
- **Auto-connect on startup** / **Minimize to tray on close** /
  **Auto-update subscriptions**.
- **Subscription User-Agent** — pick a client preset (clash, v2rayNG,
  hiddify, …) or the default `socksicle`.
- **Ping method** — HTTP GET, HTTP HEAD, or TCP connect.
- **Fake X-hwid header** — optionally spoof the `X-hwid` header expected by
  some panels (custom value, or auto-generated from machine identifiers).
- **TwinSock key** — the personal key that signs and unlocks `tws2://`
  shares; generated on first launch.

## Engines

| Engine | Protocols | Auto-download | Notes |
| ------ | --------- | ------------- | ----- |
| `sslocal` (shadowsocks-rust, pinned v1.24.0) | Shadowsocks | yes | Static musl builds on Linux; Windows x64 only |
| `xray` (Xray-core, pinned v25.4.3) | Shadowsocks, VLESS, VMess | yes | TLS / REALITY, ws / grpc / xhttp transports |
| `sing-box` (pinned v1.11.8) | Shadowsocks, VLESS, VMess | yes | TLS / REALITY, ws / grpc / http transports |

Engine binaries are located in, in order: `bin/` next to the app, the
per-user config `bin/` directory, `bin/<engine>/` subdirectories, and finally
the system `PATH`. Downloads are validated (executable format + `--version`)
before being installed atomically; an existing working engine is never
replaced.

## Configuration & Storage

All settings, servers and subscriptions are stored under the per-user config
directory, no admin rights needed:

- **Linux**: `~/.config/socksicle/`
- **Windows**: `%APPDATA%\socksicle\` (logs in `%LOCALAPPDATA%\socksicle\logs`)

Files: `servers.json`, `subscriptions.json`, `settings.json`, `drawer.json`
(TwinSock vault), and `bin/` with app-managed engine binaries.

> **TwinSock v2 vault note**: passwords, keys, UUIDs and subscription URLs
> are stored as `tws2.` tokens encrypted with a key bound to this machine's
> fingerprint. Copying the config to another machine will not unlock it —
> the app then starts with an empty list and renames the foreign file to
> `<name>.foreign-<date>.json` on the next write. Config written by older
> Socksicle versions (`__obfuscated__` fields) is transparently migrated to
> the new vault on first read. Secrets are only as safe as the machine
> itself; exports contain plain-text secrets and should not be shared.
> `gen_url.html` (in the repo) is an offline tool for encoding links into
> shareable `tws2://` tokens.

## Testing

The pytest suite runs headless (`QT_QPA_PLATFORM=offscreen`) and never
touches the network or real subprocesses:

```bash
python -m pytest tests -q
```

CI (GitHub Actions) runs the same suite on every push and pull request.

## License

MIT — see the [LICENSE](LICENSE) file.