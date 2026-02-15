#!/bin/bash
set -e

# Socksicle Installer
# Installs to ~/.local/share/socksicle

APP_NAME="Socksicle"
BIN_NAME="socksicle"
INSTALL_DIR="$HOME/.local/share/socksicle"
BIN_DIR="$HOME/.local/bin"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "Installing $APP_NAME..."

# Check requirements
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed."
    exit 1
fi

# Create directories
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$ICON_DIR"
mkdir -p "$DESKTOP_DIR"

# Copy files
cp -r ui utils main.py icon.png requirements.txt "$INSTALL_DIR/"

# Create wrapper script
cat > "$BIN_DIR/$BIN_NAME" <<EOF
#!/bin/bash
export PYTHONPATH="\$PYTHONPATH:$INSTALL_DIR"
exec python3 "$INSTALL_DIR/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/$BIN_NAME"

# Copy icon
cp icon.png "$ICON_DIR/socksicle.png" 2>/dev/null || true

# Create desktop entry
cat > "$DESKTOP_DIR/socksicle.desktop" <<EOF
[Desktop Entry]
Name=$APP_NAME
Exec=$BIN_DIR/$BIN_NAME
Icon=socksicle
Type=Application
Terminal=false
Categories=Network;Proxy;
Comment=Shadowsocks GUI client
EOF

# Update desktop database
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo "Installation complete."
echo "You can launch $APP_NAME from your application menu or by running '$BIN_NAME'."
echo "Ensure $BIN_DIR is in your PATH."
