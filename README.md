# Socksicle 🧦🧊

Socksicle is a minimalist, high-performance Shadowsocks GUI client for Linux, built with PySide6 (Qt 6). It focuses on providing a modern user experience with deep system integration and an aesthetic inspired by Material Design 3.

## Key Features

- **Material Design 3 Interface**: A clean, modern UI that adheres to the latest design guidelines.
- **Subscription Management**: Full support for standard Base64-encoded subscriptions with automatic protocol filtering (Shadowsocks `ss://` only).
- **Traffic & Expiry Monitoring**: Real-time visualization of remaining data limits and subscription expiration dates.
- **Geo-Location Integration**: Automatically detects the server's country and displays the corresponding flag and IP address in the status bar.
- **Fast TCP Ping**: Multi-threaded latency checking for all servers in your list to find the fastest connection instantly.
- **User-Local Installation**: Installs directly to your home directory, requiring no root (`sudo`) privileges for the app itself.

## Requirements

- **Python 3.8+**
- **shadowsocks-rust** (The `sslocal` binary must be available in your `PATH`)

### Installing Dependencies (Shadowsocks)

- **Fedora**: `sudo dnf install shadowsocks-rust`
- **Arch Linux**: `sudo pacman -S shadowsocks-rust`
- **Ubuntu/Debian**: `sudo apt install shadowsocks-rust`

## Getting Started

### Fast Installation
Run the provided installer script to set up the application in `~/.local/share/socksicle` and create a desktop entry in your application menu:
```bash
chmod +x install.sh
./install.sh
```

### Manual Run (Development)
1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Launch the app:
   ```bash
   python main.py
   ```

## Configuration
All settings, server data, and subscriptions are securely stored in:
`~/.config/socksicle/`

## Technology Stack
- **UI Framework**: PySide6 (Qt 6)
- **Backend**: Shadowsocks-rust (`sslocal`)
- **Geolocation**: Powered by `ip-api.com`.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
