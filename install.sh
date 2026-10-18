#!/usr/bin/env bash
# Installs Blue VO!CE for Linux for the current user.
#   ./install.sh                     download Logitech's files from G HUB's update server
#   ./install.sh --depot-dir DIR     use driver_audio_apo.depot / pro_headset.depot from DIR
set -euo pipefail

APP_ID="dev.local.LghubBlueVoice"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$PREFIX/lghub-bluevoice"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
DEPOT_ARGS=()
[ "${1:-}" = "--depot-dir" ] && DEPOT_ARGS=(--depot-dir "$(cd "$2" && pwd)")

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }

say "Checking requirements"
missing=()
need() { command -v "$1" >/dev/null || missing+=("$2"); }
need python3 "python3"
python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')" 2>/dev/null \
  || missing+=("GTK4 + libadwaita for Python (Debian/Ubuntu: python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 · Fedora: python3-gobject gtk4 libadwaita · Arch: python-gobject gtk4 libadwaita)")
need wine "wine (Debian/Ubuntu: wine · Fedora: wine · Arch: wine)"
need pw-dump "PipeWire tools (pipewire-bin / pipewire-utils / pipewire)"
need pw-link "PipeWire tools (pipewire-bin / pipewire-utils / pipewire)"
need wpctl "WirePlumber (wireplumber)"
need gcc "gcc"
need x86_64-w64-mingw32-gcc "MinGW-w64 (Debian/Ubuntu: gcc-mingw-w64-x86-64 · Fedora: mingw64-gcc · Arch: mingw-w64-gcc)"
pkg-config --exists libpipewire-0.3 2>/dev/null \
  || missing+=("PipeWire headers (Debian/Ubuntu: libpipewire-0.3-dev · Fedora: pipewire-devel · Arch: libpipewire)")
if ((${#missing[@]})); then
  printf 'Missing:\n'; printf '  - %s\n' "${missing[@]}" | sort -u; exit 1
fi
echo "OK"

say "Building"
mkdir -p "$APP_DIR/bin"
x86_64-w64-mingw32-gcc -O2 -o "$APP_DIR/bin/bluevoice_host.exe" "$SRC/host/bluevoice_host.c" \
  -lole32 -loleaut32 -luuid -lpropsys
gcc -O2 -o "$APP_DIR/bin/bluevoice-bridge" "$SRC/bridge/bluevoice_bridge.c" \
  $(pkg-config --cflags --libs libpipewire-0.3) -lpthread
echo "OK"

say "Installing to $APP_DIR"
cp "$SRC"/*.py "$SRC/lghub-bluevoice.svg" "$APP_DIR/"

say "Getting Logitech's Blue VO!CE files"
if [ -f "$APP_DIR/apo/logi_audio_dts_studio_capture_apo.dll" ] && [ ${#DEPOT_ARGS[@]} -eq 0 ]; then
  echo "Already present."
else
  python3 "$APP_DIR/fetch.py" "$APP_DIR" "${DEPOT_ARGS[@]}"
fi

say "Preparing Wine"
if [ -f "$APP_DIR/wine/system.reg" ]; then
  echo "Wine prefix already set up."
else
  # No Mono/Gecko and no menu entries: the host only needs Wine's core DLLs.
  WINEPREFIX="$APP_DIR/wine" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=d;winemenubuilder.exe=d" \
    wineboot -i >/dev/null 2>&1
  echo "Created $APP_DIR/wine"
fi

say "Adding the launcher, menu entry and icon"
mkdir -p "$BIN_DIR" "$PREFIX/applications" "$PREFIX/icons/hicolor/scalable/apps"
cat > "$BIN_DIR/lghub-bluevoice" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/app.py" "\$@"
EOF
chmod +x "$BIN_DIR/lghub-bluevoice"
cp "$SRC/lghub-bluevoice.svg" "$PREFIX/icons/hicolor/scalable/apps/lghub-bluevoice.svg"
cat > "$PREFIX/applications/lghub-bluevoice.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Blue VO!CE
Comment=Logitech Blue VO!CE microphone effects for your headset
Exec=$BIN_DIR/lghub-bluevoice
Icon=lghub-bluevoice
Terminal=false
Categories=AudioVideo;Audio;Settings;
StartupWMClass=$APP_ID
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$PREFIX/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -qf "$PREFIX/icons/hicolor" 2>/dev/null || true

say "Starting the background service"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/lghub-bluevoice.service" <<EOF
[Unit]
Description=Blue VO!CE virtual microphone
After=pipewire.service wireplumber.service
Wants=pipewire.service wireplumber.service

[Service]
ExecStart=/usr/bin/env python3 $APP_DIR/engine.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now lghub-bluevoice.service
systemctl --user restart lghub-bluevoice.service
echo "Running. A new input device, “Blue VO!CE Microphone”, appears in a few seconds."

say "Done"
echo "Open “Blue VO!CE” from your menu, or run: lghub-bluevoice"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Note: $BIN_DIR is not on your PATH." ;;
esac
