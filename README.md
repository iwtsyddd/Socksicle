# Socksicle

Cross-platform proxy client for Windows and Linux.

Socksicle provides a desktop interface for managing proxy servers and subscriptions with support for Shadowsocks, VLESS, VMess and Hysteria 2.

Built with Python, PySide6 and external proxy engines such as `sslocal`, Xray and sing-box.

<p align="center">
  <img
    width="520"
    alt="Socksicle"
    src="https://github.com/user-attachments/assets/11684261-97a0-4d4a-9da1-a42133a27be9"
  />
</p>

## Features

* Windows and Linux support
* Shadowsocks, VLESS, VMess and Hysteria 2
* `sslocal`, Xray and sing-box engine support
* Subscription import and automatic updates
* TUN mode through sing-box
* Optional kill switch
* Encrypted local storage for sensitive configuration data
* HTTP, HEAD and TCP latency checks
* Parallel node testing
* System tray integration
* Automatic reconnect after unexpected engine exits
* QR code sharing
* JSON import and export
* DoH / DoT DNS configuration
* Material 3 inspired interface

## Supported protocols

| Protocol    | Engines                 |
| ----------- | ----------------------- |
| Shadowsocks | sslocal, Xray, sing-box |
| VLESS       | Xray, sing-box          |
| VMess       | Xray, sing-box          |
| Hysteria 2  | sing-box                |

Supported link formats include:

```text
ss://
vless://
vmess://
hysteria2://
hy2://
```

Subscriptions can also be imported from HTTP(S) URLs and supported subscription formats.

## Download

The latest Windows installer is available on the GitHub Releases page:

[Latest release](https://github.com/iwtsyddd/Socksicle/releases)

Linux can be installed directly from the repository.

## Installation

### Linux

```bash
git clone https://github.com/iwtsyddd/Socksicle.git
cd Socksicle

chmod +x install.sh
./install.sh
```

The installer installs Socksicle for the current user without requiring a system-wide installation.

### Windows

Install Python 3.10 or newer and then:

```powershell
pip install .
```

Run with:

```powershell
socksicle
```

or:

```powershell
python main.py
```

## Configuration

Socksicle stores its configuration in the user's application data directory.

### Linux

```text
~/.config/socksicle/
```

### Windows

```text
%APPDATA%\socksicle\
```

Depending on configuration, the directory may contain:

```text
servers.json
subscriptions.json
settings.json
drawer.json
bin/
logs/
```

Sensitive fields are stored in encrypted form using the built-in TwinSock vault.

## Proxy engines

Socksicle can use different backend engines depending on the selected protocol and mode.

| Engine     | Purpose                                    |
| ---------- | ------------------------------------------ |
| `sslocal`  | Shadowsocks                                |
| `xray`     | Shadowsocks, VLESS, VMess                  |
| `sing-box` | Shadowsocks, VLESS, VMess, Hysteria 2, TUN |

Missing engine binaries can be downloaded by Socksicle or installed manually.

## TUN mode

TUN mode routes system traffic through a virtual network interface using sing-box.

On Linux, Socksicle can use Polkit and Linux capabilities instead of running the entire application as root.

TUN mode is currently marked as beta.

## Security

Socksicle encrypts sensitive local configuration fields instead of storing them as plain text.

The current vault uses:

* AES-256-GCM
* HKDF-SHA256
* machine-bound key derivation

The encryption layer is intended to protect stored configuration data on the local machine. It does not make the proxy connection itself anonymous or guarantee protection against every possible system-level attack.

See [SECURITY.md](SECURITY.md) for the security model and vulnerability reporting process.

## Development

Clone the repository and install development dependencies:

```bash
git clone https://github.com/iwtsyddd/Socksicle.git
cd Socksicle

pip install -e ".[dev]"
```

Run the test suite:

```bash
python -m pytest tests -q
```

The project also runs the test suite in GitHub Actions on Windows and Linux.

## Project structure

```text
Socksicle/
├── ui/          # Qt interface
├── utils/       # networking, engines, storage and platform code
├── tests/       # test suite
├── data/        # application data
├── main.py      # application entry point
├── install.sh   # Linux installer
└── pyproject.toml
```

## License

MIT. See [LICENSE](LICENSE).
