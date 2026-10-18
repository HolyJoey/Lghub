#!/usr/bin/env bash
# Removes Lghub (and its Blue VO!CE service). Settings and saved presets in ~/.config are kept unless you ask.
set -euo pipefail

PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$PREFIX/lghub-bluevoice"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/lghub-bluevoice"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/lghub-bluevoice.service"

systemctl --user disable --now lghub-bluevoice.service 2>/dev/null || true
rm -f "$UNIT"
systemctl --user daemon-reload 2>/dev/null || true

rm -rf "$APP_DIR"
rm -f "$HOME/.local/bin/lghub" "$HOME/.local/bin/lghub-bluevoice"
rm -f "$PREFIX/applications/lghub-bluevoice.desktop"
rm -f "$PREFIX/icons/hicolor/scalable/apps/lghub-bluevoice.svg" "$PREFIX/icons/hicolor/256x256/apps/lghub.png"
if command -v update-desktop-database >/dev/null; then update-desktop-database "$PREFIX/applications" || true; fi
echo "App, background service and Logitech files removed."

if [ -d "$CONFIG_DIR" ]; then
  read -rp "Also delete your settings and saved presets in $CONFIG_DIR? [y/N] " reply
  [[ ${reply:-N} =~ ^[Yy]$ ]] && rm -rf "$CONFIG_DIR" && echo "Settings deleted."
fi
