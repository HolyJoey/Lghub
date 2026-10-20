#!/usr/bin/env bash
# Removes Lghub and its background service. Settings and saved presets in ~/.config are kept unless you ask.
# Also cleans up an install from when Lghub was called lghub-bluevoice.
set -euo pipefail

PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_DIR="$CONFIG_HOME/lghub"

for name in lghub lghub-bluevoice; do
  systemctl --user disable --now "$name.service" 2>/dev/null || true
  rm -f "$CONFIG_HOME/systemd/user/$name.service"
  rm -rf "${PREFIX:?}/$name"
  rm -f "$HOME/.local/bin/$name" "$PREFIX/applications/$name.desktop"
done
systemctl --user daemon-reload 2>/dev/null || true
rm -f "$PREFIX/icons/hicolor/scalable/apps/lghub-logo.svg" "$PREFIX/icons/hicolor/scalable/apps/lghub-bluevoice.svg" \
  "$PREFIX/icons/hicolor/256x256/apps/lghub.png"
if command -v update-desktop-database >/dev/null; then update-desktop-database "$PREFIX/applications" || true; fi
echo "App, background service and Logitech files removed."

for dir in "$CONFIG_DIR" "$CONFIG_HOME/lghub-bluevoice"; do
  if [ -d "$dir" ]; then
    read -rp "Also delete your settings and saved presets in $dir? [y/N] " reply
    [[ ${reply:-N} =~ ^[Yy]$ ]] && rm -rf "$dir" && echo "Settings deleted."
  fi
done
