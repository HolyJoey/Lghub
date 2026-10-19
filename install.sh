#!/usr/bin/env bash
# Installs Lghub (Logitech G devices on Linux, with Blue VO!CE) for the current user.
# No root needed; mice and keyboards also want the udev rule printed at the end.
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
need pw-dump "PipeWire tools (pipewire-bin / pipewire-utils / pipewire)"
need pw-link "PipeWire tools (pipewire-bin / pipewire-utils / pipewire)"
need wpctl "WirePlumber (wireplumber)"
need amixer "ALSA utilities (alsa-utils)"
need gcc "gcc"
pkg-config --exists libpipewire-0.3 2>/dev/null \
  || missing+=("PipeWire headers (Debian/Ubuntu: libpipewire-0.3-dev · Fedora: pipewire-devel · Arch: libpipewire)")
if ((${#missing[@]})); then
  printf 'Missing:\n'; printf '  - %s\n' "${missing[@]}" | sort -u; exit 1
fi
echo "OK"

say "Building"
[ "$(uname -m)" = x86_64 ] || { echo "Blue VO!CE's DSP is x86-64 code; this machine is $(uname -m)."; exit 1; }
mkdir -p "$APP_DIR/bin"
read -ra PW_FLAGS <<< "$(pkg-config --cflags --libs libpipewire-0.3)"
gcc -O2 -o "$APP_DIR/bin/bluevoice-bridge" \
  "$SRC/bridge/bluevoice_bridge.c" "$SRC/bridge/micopt.c" "$SRC/bridge/bv2.c" "$SRC/bridge/peloader.c" \
  "${PW_FLAGS[@]}" -lm
gcc -O2 -o "$APP_DIR/bin/surround-bridge" \
  "$SRC/bridge/surround_bridge.c" "$SRC/bridge/hx2e.c" "$SRC/bridge/peloader.c" \
  "${PW_FLAGS[@]}" -lm
# Earlier versions ran the DSP under Wine; that's no longer needed.
rm -rf "$APP_DIR/wine" "$APP_DIR/bin/bluevoice_host.exe"
echo "OK"

say "Installing to $APP_DIR"
cp "$SRC"/*.py "$SRC/lghub-bluevoice.svg" "$APP_DIR/"

say "Getting Logitech's audio effects"
if [ -f "$APP_DIR/apo/logi_audio_dts_studio_capture_apo.dll" ] \
   && [ -f "$APP_DIR/apo/logi_audio_hx2e_render_apo.dll" ] && [ ${#DEPOT_ARGS[@]} -eq 0 ]; then
  echo "Already present."
else
  python3 "$APP_DIR/fetch.py" "$APP_DIR" "${DEPOT_ARGS[@]}"
fi

say "Adding the launcher, menu entry and icon"
mkdir -p "$BIN_DIR" "$PREFIX/applications" "$PREFIX/icons/hicolor/scalable/apps"
for launcher in lghub lghub-bluevoice; do
  cat > "$BIN_DIR/$launcher" <<EOF
#!/usr/bin/env bash
exec python3 "$APP_DIR/app.py" "\$@"
EOF
  chmod +x "$BIN_DIR/$launcher"
done
cp "$SRC/lghub-bluevoice.svg" "$PREFIX/icons/hicolor/scalable/apps/lghub-bluevoice.svg"
python3 "$APP_DIR/depots.py" --eq-presets "$APP_DIR/presets/equalizer_presets.json" || true
# The G HUB icon, read from Logitech's update server (six small requests); ours if that fails.
ICON=lghub-bluevoice
mkdir -p "$PREFIX/icons/hicolor/256x256/apps"
if python3 "$APP_DIR/depots.py" --app-icon "$PREFIX/icons/hicolor/256x256/apps/lghub.png"; then
  ICON=lghub
fi
cat > "$PREFIX/applications/lghub-bluevoice.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Lghub
GenericName=Logitech G devices
Comment=Settings for Logitech G headsets, mice and webcams, with Blue VO!CE
Exec=$BIN_DIR/lghub
Icon=$ICON
Terminal=false
Categories=AudioVideo;Audio;Settings;HardwareSettings;
StartupWMClass=$APP_ID
EOF
if command -v update-desktop-database >/dev/null; then update-desktop-database "$PREFIX/applications" || true; fi
if command -v gtk-update-icon-cache >/dev/null; then gtk-update-icon-cache -qf "$PREFIX/icons/hicolor" 2>/dev/null || true; fi

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
echo "Running. A new input device, 'Blue VO!CE Microphone', appears in a few seconds."

say "Done"
echo "Open 'Lghub' from your menu, or run: lghub"
if ! grep -qs uinput /etc/udev/rules.d/70-lghub.rules; then
  cat <<'RULES'

Mice, keyboards and macros need a udev rule (the only step that needs root):
  printf '%s\n' 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", TAG+="uaccess"' \
    'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' \
    | sudo tee /etc/udev/rules.d/70-lghub.rules
  sudo udevadm control --reload && sudo udevadm trigger
RULES
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Note: $BIN_DIR is not on your PATH." ;;
esac
