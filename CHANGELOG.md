# Changelog

All notable changes to Socksicle are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.1] - 2026-08-16

> **Linux reliability patch.** Socksicle fixes the power toggle silently doing
> nothing on Linux (a swallowed `NameError` in the TUN path), makes the settings
> dropdowns render opaquely instead of turning transparent, brings file logging
> and an unhandled-exception hook to Linux, and gives the app a consistent
> Fusion dark theme on Linux desktops.

### Added

- 🐧 **Linux logging & crash visibility**: file logging and the unhandled-
  exception hook now run on Linux too (`~/.config/socksicle/socksicle/logs/`),
  so startup and runtime errors are no longer invisible —
  `utils/platform_startup.py`.
- 🎨 **Consistent Linux theming**: on non-Windows platforms the app forces the
  `Fusion` style with a Material 3 dark `QPalette`, so widgets no longer depend
  on the desktop theme — `main.py`.
- 🪟 **Platform-aware translucent windows**: the frameless window attributes are
  now decided per session (compositing-safe on Windows/Wayland; opaque fallback
  on bare X11, override with `SOCKSICLE_TRANSLUCENT=0`) —
  `utils/window_utils.py`.
- 🛡️ TUN Mode reports a readable error when `/dev/net/tun` is missing or
  unusable instead of failing silently — `utils/engines/singbox_engine.py`.

### Changed

- 🔧 `is_admin()` / `elevate_restart()` now cover Linux (`geteuid`, `pkexec`
  with a `sudo` fallback) while the Windows paths stay untouched —
  `utils/platform_utils.py`.

### Fixed

- 🧯 Fixed the VPN power toggle appearing dead on Linux: the connect handler
  referenced `sys.platform` without importing `sys`, raising a `NameError` that
  Qt silently swallowed whenever TUN Mode was enabled — `ui/main_window.py`.
- 🧯 TUN Mode now works on Linux: root is detected via `geteuid`, elevation goes
  through `pkexec`/`sudo`, and both the privilege prompt and the failure dialog
  are explained in plain language instead of failing silently —
  `utils/platform_utils.py`, `ui/main_window.py`.
- 🧯 Fixed the settings dropdowns (QComboBox) rendering transparent on Linux:
  the `::drop-down` column, the popup container and the item-view corners are now
  painted with opaque theme colors, and the dialog-card `QFrame` rule no longer
  leaks into the popup — `ui/settings_dialog.py`.
- 🧯 The toggle switch now reliably flips back OFF when a connection fails; the
  `QMetaObject.invokeMethod` call targets a real `@Slot(bool)` —
  `ui/toggle_switch.py`, `ui/main_window.py`.

## [1.4] - 2026-08-16

> **Current release.** Socksicle introduces Material You (Material 3) dynamic theming
> with live wallpaper accent extraction, system-wide TUN mode (Global VPN), Hysteria 2
> protocol support, standalone draggable windows for Settings and Connection Logs, and
> major connection lifecycle improvements.

### Added

- 🎨 **Material You (Material 3) dynamic theming engine**:
  - Full Material 3 tonal palette generation (`primary`, `primary_container`,
    `secondary_container`, `surface`, `surface_container`, `surface_container_high`,
    `outline`, `outline_variant`, `on_primary`, etc.) with WCAG-compliant contrast
    calculations — `utils/theme.py`.
  - Built-in curated M3 color presets (Dynamic System/Wallpaper, Cobalt, Sage,
    Amber, Rose, Crimson, Obsidian, Arctic) selectable in Settings with instant
    **Live Preview** — `ui/settings_dialog.py`, `utils/theme.py`.
  - **Hot-Plug system accent & wallpaper monitor**: background polling timer
    detects Windows DWM accent color and wallpaper changes in real time, seamlessly
    re-theming all active windows and widgets on the fly — `utils/theme.py`,
    `ui/main_window.py`.
- 🛡️ **TUN Mode (Global Transparent Proxy / VPN)**:
  - System-wide traffic routing via `sing-box` TUN inbound and Wintun driver
    with DNS hijacking and sniff routing rules — `utils/engines/singbox_engine.py`.
  - Automatic Administrator elevation prompt and restart on Windows when TUN Mode
    is enabled — `ui/main_window.py`, `utils/platform_utils.py`.
  - Dynamic per-session virtual adapter generation (`socksicle-{id}`) and stale
    adapter cleanup routines preventing Wintun device naming collisions and
    error `0x000000B7` (`Cannot create a file when that file already exists`) —
    `utils/engines/singbox_engine.py`.
  - Clean graceful shutdown (`CTRL_BREAK_EVENT`) ensuring Wintun properly releases
    adapter handles and restores Windows routing tables before termination —
    `utils/engines/base.py`.
  - Non-blocking asynchronous connection flow with dynamic `"🔧 Creating tunnel..."`
    status indication and immediate UI feedback — `ui/main_window.py`,
    `utils/connection_manager.py`.
- ⚡ **Hysteria 2 (hy2) protocol support**:
  - Link parser for `hy2://` and `hysteria2://` URIs with port hopping,
    obfuscation, SNI, and insecure TLS flags — `utils/link_parser.py`.
  - Sing-box outbound configuration generator for Hysteria 2 —
    `utils/engines/singbox_engine.py`.
- 📋 **Standalone Window Architecture**:
  - **Connection Log Window** (`ConnectionLogDialog`): Converted to a standalone,
    draggable frameless window (`560×520`) with clean monospace typography, ANSI
    escape sequence stripping, auto-scrolling, and dynamic theme synchronization —
    `ui/connection_log_dialog.py`.
  - **Settings Window** (`SettingsDialog`): Standalone frameless window with
    Material 3 outlines, custom rounded inputs, dropdowns, and spinboxes —
    `ui/settings_dialog.py`.
  - **About Window** (`AboutDialog`): Material 3 styled dialog with live theming
    and GitHub project link — `ui/about_dialog.py`.

### Changed

- 🔄 **Sing-box config modernized for v1.12+**: deprecated legacy DNS fields and
  inbound keys migrated to rule actions (`sniff`, `hijack-dns`, `ip_is_private`),
  and TUN inbound updated to the standard `address` array format —
  `utils/engines/singbox_engine.py`.
- 🔕 **Streamlined engine log draining**: normal informational output from
  `stderr` is now cleanly classified as `[sing-box (TUN)-log]` without misleading
  error prefixes — `utils/engines/base.py`.
- 💊 **Material 3 pill tabs and cleaned button styling**: subscription tabs
  redesigned as rounded pill chips (`border-radius: 16px`), dotted focus outlines
  removed across the entire UI (`setFocusPolicy(Qt.NoFocus)`), and server badges
  given clean transparent styling — `ui/main_window.py`, `ui/server_item.py`.
- ⏱️ **Extended probe timeout**: connection probe timeout increased to 25s to
  gracefully accommodate Windows virtual adapter driver initialization —
  `utils/connection_manager.py`.
- 🖥️ **High-DPI policy initialization**: scale-factor rounding policy is now
  applied statically before `QApplication` instantiation to eliminate Qt 6 startup
  warnings — `utils/platform_startup.py`, `main.py`.

### Fixed

- 🧯 Fixed VPN toggle switch staying in the ON state when a connection failed to
  start; switch now reliably flips back to OFF on error or disconnect.
- 🧯 Fixed bottom navigation buttons (`Settings`, `Logs`, `About`) and dialog
  containers retaining initial theme colors after palette switches.
- 🧯 Fixed server list title clipping and empty ping badge layout displacement.
- 🧯 Fixed VLESS TLS WebSocket compatibility by stripping incompatible TCP-only
  `flow` flags.

## [1.3] - 2026-08-15

> **Previous release.** Socksicle grows from a Linux-only Shadowsocks client into a
> multi-protocol proxy client for Windows and Linux with selectable engines
> (sslocal / xray / sing-box), VLESS and VMess support, an encrypted machine-bound
> config vault, richer subscription metadata and a reworked latency-ping pipeline.

### Added

- 🌐 **Windows support**: native installer (`install_win.bat`), high-DPI
  environment and scale-factor policy, `AppUserModelID` for taskbar grouping,
  unhandled-exception logging, tray-icon persistence after Explorer restarts
  (`WM_TASKBARCREATED`) and automatic proxy re-connect after sleep/hibernate
  resume (`WM_POWERBROADCAST`) — `utils/platform_startup.py`,
  `utils/platform_utils.py`, `install_win.bat`.
- 🚀 **Xray-core and sing-box engines** alongside sslocal, switchable in
  Settings — `utils/engines/base.py`, `utils/engines/engine_manager.py`,
  `utils/engines/xray_engine.py`, `utils/engines/singbox_engine.py`,
  `utils/engines/sslocal_engine.py`.
- 📦 **Engine auto-install pipeline**: pinned-release download (with parallel
  byte-range download when the server supports it), archive extraction,
  `--version` validation and atomic install with version markers —
  `utils/engines/common.py`; backend provisioning with a progress dialog
  (speed + ETA) at startup — `utils/startup_utils.py`.
- 🧹 **Stale engine-process cleanup**: PID markers let the app kill engine
  processes a crashed session left behind so local ports are never held by
  zombies — `utils/engines/proc_guard.py`.
- ✨ **VLESS and VMess protocol support** (including TLS/Reality and WS/gRPC/XHTTP
  transports) via `utils/server_model.py` and `utils/link_parser.py`; the ss
  parser now also handles SIP002 plugins and AEAD-2022 userinfo —
  `utils/ss_parser.py`.
- 🏷️ **Protocol badges** in the server list (e.g. `VLESS · Reality · WS`,
  `SS · Plugin`) — `ui/server_item.py`.
- 🔐 **TwinSock v2 vault**: passwords, UUIDs, keys and subscription URLs are
  encrypted at rest with keys derived from a machine fingerprint, so config
  files are useless on other machines (foreign configs are detected and
  retired); chain hashes detect external tampering; legacy `__obfuscated__`
  configs are migrated automatically — `utils/twinsock.py`.
- 🔗 **`tws2://` encrypted share links**: share any server or subscription as
  an encrypted token signed with your personal key (auto-generated, shown in
  Settings) — `utils/twinsock.py`, `ui/main_window.py`, `ui/add_server_dialog.py`.
- 📤📥 **Export/import rewritten** on a transport form with schema markers and
  legacy-format migration — `utils/twinsock.py` (`export_payload` /
  `import_payload`), `utils/server_manager.py`.
- 🔄 **Richer subscription metadata**: SIP008 JSON subscriptions, extended
  headers (`Profile-Title`, `Profile-Description`, `Profile-Update-Interval`,
  `Support-URL`, `Profile-Web-Page-URL`, `Announce`, `Content-Disposition`)
  including panels' `base64:`-prefixed values, and body-preamble description
  extraction — `utils/sub_manager.py` (`_decode_maybe_base64`,
  `_extract_metadata`, `_extract_description`, `_try_parse_sip008_json`).
- 📢 **Subscription description display**: profile title/description and
  update info are shown centered in the traffic card when a subscription tab
  is active — `ui/main_window.py` (`switch_tab`).
- 🛡️ **Subscription URL validation**: only `http`/`https` schemes are
  accepted and targets resolving to private/loopback/link-local IPs are
  rejected — `utils/sub_manager.py` (`parse_subscription`).
- 🧭 **Subscription User-Agent presets and fake `X-hwid` header** for panels
  that filter by client — `utils/sub_manager.py`, `ui/settings_dialog.py`.
- ⏰ **Subscription auto-update** with a per-subscription refresh interval
  (`Profile-Update-Interval`) — `utils/subscription_manager.py`.
- ⚡ **Selectable ping methods** (`http_get` / `http_head` / `tcp_connect`):
  "Ping All" now uses the method chosen in Settings, pinging through the local
  SOCKS5 proxy when it is up (with direct-HTTP fallback) or directly with
  `tcp_connect`; the active connection is always pinged with HTTP HEAD against
  `connectivitycheck.gstatic.com/generate_204` — `utils/ping.py`,
  `ui/main_window.py` (`ping_all_servers`), `utils/connection_manager.py`.
- ✅ **Verified connectivity**: "Connected" is only reported after the local
  proxy answers a real SOCKS5 handshake probe, not after a fixed startup
  delay — `utils/connection_manager.py`, `utils/ping.py`
  (`socks5_proxy_ready`).
- 🧪 **Automated test suite** (18 test modules), GitHub Actions CI for Linux +
  Windows on Python 3.10–3.12, and `CONTRIBUTING.md`.
- 🪟 Windows-specific error hints for missing/outdated Microsoft Visual C++
  runtimes (`0xC0000135` / `0xC0000139`) — `utils/engines/base.py`.

### Changed

- 🔧 sslocal now runs through the same engine framework as xray/sing-box and
  receives a config file instead of command-line arguments (no password on
  the command line).
- 🌍 Geo-IP lookup rewritten with strict HTTP response parsing (chunked /
  Content-Length framing, header and body size limits) instead of naive
  recv-loop parsing — `utils/geo_utils.py`.
- 🔠 Simplified ping-method labels in Settings (HTTP GET / HTTP HEAD /
  TCP connect) — `ui/settings_dialog.py`.
- ⚙️ `pyproject.toml`: `requires-python` bumped to `>=3.10`; dev extras
  (`pytest`, `pytest-cov`) added; classifiers now cover Windows.

### Fixed

- 🛠️ sing-box: private/loopback address traffic is now routed through the
  `direct` outbound via the `ip_is_private` rule instead of being proxied —
  `utils/engines/singbox_engine.py`.
- 🧯 Port-in-use failures are translated into actionable hints naming the
  conflicting local/API port — `utils/engines/base.py` (`_bind_error_hint`).
- 🔇 Removed the stale forced "Connected" status after a fixed timeout; the UI
  now stays honest until the proxy handshake probe succeeds.

### Security

- 🔐 Config secrets (passwords, UUIDs, keys, subscription URLs, share keys)
  are stored encrypted, bound to the local machine (TwinSock v2 vault);
  foreign configurations cannot be decrypted and are retired.
- 🛡️ Subscription fetches reject non-`http(s)` schemes and private/loopback
  IP targets.
- 🔒 Engine config temp files are created with `0600` permissions on POSIX.

### Removed

- 🗑️ `utils/ss_client.py` (replaced by the engine abstraction).
- 🗑️ The blocking startup check that refused to launch when `sslocal` was
  missing; the app now provisions the backend on demand.

## [1.2] - 2026-02-16

### Added

- 📤📥 **Profile Export/Import**: one-click JSON backup/restore of servers and
  subscriptions (📤 / 📥 toolbar buttons).
- 🔍 **Instant Search**: live filtering of the server list by name or IP.
- 🪟 **"Minimize to tray on close"** option in Settings; closing the window
  no longer disconnects or quits when enabled.
- 🔔 **Update result notifications**: subscription updates report exactly what
  happened — "Added +X new nodes" when new servers appeared, "Already up to
  date" otherwise.

### Changed

- 🌍 Geo-IP fetch rewritten to run directly over the SOCKS5 socket (raw HTTP
  exchange), improving stability of the connection-status flow.

## [1.1] - 2026-02-15

### Added

- 🖥️ **Tray Icon (Beta)**: control the connection and switch servers directly
  from the system tray.
- 📲 **Share Config**: generate a QR code for any server node to share it with
  mobile devices — `ui/server_item.py`.
- 🔔 **Native notifications** for connection status and errors.
- 🔄 **One-click subscription Update** button to refresh server lists
  instantly.
- ℹ️ **About dialog**.
- 🟢 Explicit "Connecting…" state with a "Connected" fallback, replacing the
  earlier silent connect flow.

### Changed

- 🌐 **Fixed Geo-IP Verification**: the public IP and country flag are now
  fetched strictly through the SOCKS5 tunnel, providing visual confirmation
  that the proxy actually works.
- ⚡ **Stability**: faster engine process detection (startup timeout lowered,
  retry loop removed) and reworked status handling to eliminate the
  "Infinite Connecting" state.

## [1.0] - 2026-02-15

Initial public release.

### Added

- 🎨 **Material Design 3 interface** rebuilt from the ground up with PySide6
  (Qt 6) — including dynamic wallpaper theming (GNOME) that generates a
  matching M3 color palette.
- 🔄 **Subscription Support**: add Shadowsocks subscriptions by URL; Base64
  link lists are parsed automatically and filtered for `ss://` links.
- 📊 **Traffic & Expiry Monitoring**: remaining data limits and subscription
  expiration dates from the `Subscription-Userinfo` header, visualized with a
  progress bar.
- 🌍 **Geolocation Integration**: automatic country detection with flag emoji
  and IP shown in the status area when connected.
- ⚡ **Multi-threaded TCP Ping**: instant "Ping All" latency check across the
  whole server list.
- 🧦 **Shadowsocks-rust backend** (`sslocal`) with distro-aware install
  instructions for Fedora, Arch, Ubuntu/Debian and openSUSE.
- 🧑‍💻 **Rootless installation**: the installer sets the app up in
  `~/.local/share/socksicle` with a desktop entry — no `sudo` required.