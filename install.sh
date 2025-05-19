#!/bin/bash
set -e
INSTALL_DIR="$(pwd)"
ICON_PATH="$INSTALL_DIR/icon.png"
DESKTOP_FILE="/usr/share/applications/Socksicle.desktop"
echo "🧷 Creating desktop shortcut at $DESKTOP_FILE..."
echo "[Desktop Entry]
Name=Socksicle
Exec=python3 $INSTALL_DIR/main.py
Icon=$ICON_PATH
Type=Application
Terminal=false
Categories=Network;" | sudo tee "$DESKTOP_FILE" > /dev/null
sudo chmod +x "$DESKTOP_FILE"
sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
echo "✅ Installation complete!"
echo "🚀 Launch with: python3 $INSTALL_DIR/main.py"
