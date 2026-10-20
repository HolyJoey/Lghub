#!/usr/bin/env bash
# Installs Lghub (Logitech G devices on Linux, with Blue VO!CE) for the current user.
# No root needed, except to install missing packages and the udev rule for mice and keyboards;
# for both it shows the exact command and asks first (the default is no).
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

OS_RELEASE="${LGHUB_OS_RELEASE:-/etc/os-release}"     # the tests point these at fakes
OSTREE_MARK="${LGHUB_OSTREE_MARK:-/run/ostree-booted}"
SUDO="${LGHUB_SUDO:-sudo}"

os_field() {
  # shellcheck source=/dev/null
  [ -r "$OS_RELEASE" ] && (. "$OS_RELEASE"; eval "printf '%s' \"\${$1:-}\"")
}

# apt, dnf or pacman for this system, or nothing where packages can't (or shouldn't) be installed
# this way: unknown distributions and image-based ones (Silverblue, SteamOS, NixOS).
package_manager() {
  local id
  id="$(os_field ID)"
  case "$id" in steamos|nixos) return ;; esac
  [ -e "$OSTREE_MARK" ] && return
  for id in $id $(os_field ID_LIKE); do
    case "$id" in
      debian|ubuntu) echo apt; return ;;
      fedora|rhel) echo dnf; return ;;
      arch) echo pacman; return ;;
    esac
  done
}

# The packages for one requirement on one package manager.
packages() {
  case "$1:$2" in
    pacman:python) echo python ;;
    *:python) echo python3 ;;
    apt:gtk) echo python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ;;
    dnf:gtk) echo python3-gobject gtk4 libadwaita ;;
    pacman:gtk) echo python-gobject gtk4 libadwaita ;;
    pacman:crypto) echo python-cryptography ;;
    *:crypto) echo python3-cryptography ;;
    apt:pwtools) echo pipewire-bin ;;
    dnf:pwtools) echo pipewire-utils ;;
    pacman:pwtools) echo pipewire ;;
    *:wireplumber) echo wireplumber ;;
    *:alsa) echo alsa-utils ;;
    *:gcc) echo gcc ;;
    apt:pkgconfig) echo pkg-config ;;
    dnf:pkgconfig) echo pkgconf-pkg-config ;;
    pacman:pkgconfig) echo pkgconf ;;
    apt:headers) echo libpipewire-0.3-dev ;;
    dnf:headers) echo pipewire-devel ;;
    pacman:headers) echo libpipewire ;;
    apt:screen) echo gir1.2-gstreamer-1.0 gstreamer1.0-pipewire ;;
    dnf:screen) echo pipewire-gstreamer ;;
    pacman:screen) echo gst-plugin-pipewire ;;
    *:tray) echo gnome-shell-extension-appindicator ;;
  esac
}

interactive() { [ -t 0 ] || [ -n "${LGHUB_INTERACTIVE:-}" ]; }

# Show the command that installs these packages and run it on a yes (the default is no).
offer() {
  local question="$1" manager="$2"; shift 2
  local cmd
  case "$manager" in
    apt) cmd=(apt install "$@") ;;
    dnf) cmd=(dnf install "$@") ;;
    pacman) cmd=(pacman -S --needed "$@") ;;
  esac
  echo
  echo "This command installs them:"
  echo "  sudo ${cmd[*]}"
  interactive || return 1
  local answer=""
  read -r -p "$question [y/N] " answer || true
  case "$answer" in
    y|Y|yes|Yes) "$SUDO" "${cmd[@]}" ;;
    *) return 1 ;;
  esac
}

# The packages for a list of requirement keys, each once.
packages_for() {
  local manager="$1" key pkg seen=" "; shift
  for key in "$@"; do
    for pkg in $(packages "$manager" "$key"); do
      case "$seen" in *" $pkg "*) ;; *) seen="$seen$pkg "; printf '%s\n' "$pkg" ;; esac
    done
  done
}

say "Checking requirements"
[ "$(uname -m)" = x86_64 ] || { echo "Blue VO!CE's DSP is x86-64 code; this machine is $(uname -m)."; exit 1; }
missing=()
keys=()
need() { command -v "$1" >/dev/null || { keys+=("$2"); missing+=("$3"); }; }
need python3 python "Python 3"
python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1')" 2>/dev/null \
  || { keys+=(gtk); missing+=("GTK 4 and libadwaita for Python"); }
python3 -c "import cryptography" 2>/dev/null || { keys+=(crypto); missing+=("Python cryptography (newer G HUB packages)"); }
need pw-dump pwtools "PipeWire tools (pw-dump, pw-link)"
need pw-link pwtools "PipeWire tools (pw-dump, pw-link)"
need wpctl wireplumber "WirePlumber (wpctl)"
need amixer alsa "ALSA utilities (amixer)"
need gcc gcc "gcc"
need pkg-config pkgconfig "pkg-config"
pkg-config --exists libpipewire-0.3 2>/dev/null || { keys+=(headers); missing+=("PipeWire headers"); }
if ((${#missing[@]})); then
  manager="$(package_manager)"
  system="$(os_field PRETTY_NAME || true)"
  echo "Missing on ${system:-this system}:"
  printf '%s\n' "${missing[@]}" | awk '!seen[$0]++ { print "  - " $0 }'
  if [ -n "$manager" ] && [ -z "${LGHUB_RETRIED:-}" ]; then
    mapfile -t pkgs < <(packages_for "$manager" "${keys[@]}")
    if offer "Run it now?" "$manager" "${pkgs[@]}"; then
      LGHUB_RETRIED=1 exec "$0" "$@"        # check again with them installed
    fi
    echo
    echo "Install them, then run ./install.sh again."
  elif [ -n "${LGHUB_RETRIED:-}" ]; then
    echo
    echo "Still missing after installing them: ${system:-this system} may name these packages"
    echo "differently. Please open an issue with the list above."
  else
    echo
    echo "Install these with your distribution's packages (the README has the names for Debian /"
    echo "Ubuntu, Fedora and Arch), then run ./install.sh again."
  fi
  exit 1
fi
systemctl --user show-environment >/dev/null 2>&1 \
  || { echo "The background service needs systemd user services (systemctl --user), which aren't available here."; exit 1; }
if ! wpctl status >/dev/null 2>&1; then
  echo "PipeWire isn't running in this session (Lghub's audio parts need it, not PulseAudio)."
  echo "Most distributions switch with their pipewire-pulse package; log out and in afterwards."
  exit 1
fi
echo "OK"

# Optional: only some features need these; Lghub works without them.
optional=()
extras=()
command -v grim >/dev/null \
  || python3 -c "import gi; gi.require_version('Gst','1.0'); from gi.repository import Gst; Gst.init(None); assert Gst.ElementFactory.find('pipewiresrc')" 2>/dev/null \
  || { extras+=(screen); optional+=("Screen sampler (LIGHTSYNC): GStreamer's PipeWire plugin (or grim on Hyprland / Sway)"); }
if [ "${XDG_CURRENT_DESKTOP:-}" != "${XDG_CURRENT_DESKTOP#*GNOME}" ]; then
  extras+=(tray); optional+=("Tray icon on GNOME: the AppIndicator extension (switch it on in Extensions afterwards)")
fi
if ((${#optional[@]})); then
  echo
  echo "Optional, for some features:"
  printf '  - %s\n' "${optional[@]}"
  manager="$(package_manager)"
  if [ -n "$manager" ]; then
    mapfile -t pkgs < <(packages_for "$manager" "${extras[@]}")
    offer "Install these too?" "$manager" "${pkgs[@]}" || echo "Skipped; Lghub works without them."
  fi
fi

say "Building"
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
UDEV_RULES="${LGHUB_UDEV_RULES:-/etc/udev/rules.d/70-lghub.rules}"
# hidraw of Logitech USB devices and of Logitech Bluetooth devices (HID bus 0005), and uinput
RULES='SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", TAG+="uaccess"
SUBSYSTEM=="hidraw", KERNELS=="0005:046D:*", TAG+="uaccess"
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"'
if ! grep -qs '0005:046D' "$UDEV_RULES"; then   # missing, or from before Bluetooth support
  echo
  cat <<TEXT
Mice, keyboards and macros need a udev rule (the only step that needs root). These commands
set it up:
  sudo tee $UDEV_RULES >/dev/null <<'RULES'
$RULES
RULES
  sudo udevadm control --reload && sudo udevadm trigger
TEXT
  answer=""
  if interactive; then read -r -p "Run them now? [y/N] " answer || true; fi
  case "$answer" in
    y|Y|yes|Yes)
      printf '%s\n' "$RULES" | "$SUDO" tee "$UDEV_RULES" >/dev/null
      "$SUDO" udevadm control --reload && "$SUDO" udevadm trigger
      echo "Done: unplug and replug your devices (or log out and in) if they don't show up." ;;
  esac
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Note: $BIN_DIR is not on your PATH." ;;
esac
