#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTML_FILE="$SCRIPT_DIR/gen_url.html"

if [ ! -f "$HTML_FILE" ]; then
    HTML_FILE="$SCRIPT_DIR/ui/gen_url.html"
fi

if [ ! -f "$HTML_FILE" ]; then
    echo "[ERROR] Could not locate gen_url.html in $SCRIPT_DIR" >&2
    exit 1
fi

if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$HTML_FILE" >/dev/null 2>&1 &
elif command -v sensible-browser >/dev/null 2>&1; then
    sensible-browser "$HTML_FILE" >/dev/null 2>&1 &
elif command -v gio >/dev/null 2>&1; then
    gio open "$HTML_FILE" >/dev/null 2>&1 &
elif command -v x-www-browser >/dev/null 2>&1; then
    x-www-browser "$HTML_FILE" >/dev/null 2>&1 &
elif command -v firefox >/dev/null 2>&1; then
    firefox "$HTML_FILE" >/dev/null 2>&1 &
elif command -v google-chrome >/dev/null 2>&1; then
    google-chrome "$HTML_FILE" >/dev/null 2>&1 &
elif command -v chromium >/dev/null 2>&1; then
    chromium "$HTML_FILE" >/dev/null 2>&1 &
else
    echo "[ERROR] No supported browser or xdg-open found to open $HTML_FILE" >&2
    echo "Please open file://$HTML_FILE directly in your web browser."
    exit 1
fi

exit 0
