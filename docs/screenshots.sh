#!/bin/bash
# Renders docs/screenshots/*.png without touching the real screen: the app runs on GTK's
# Broadway backend and draws itself to a file. Mice and keyboards are the simulated ones
# (simulate.py); the webcam shot uses whatever camera is at USB port $CAMERA_PORT.
# Needs gtk4-broadwayd, and the app installed (Blue VO!CE pages show the running engine).
set -u
DOCS="$(cd "$(dirname "$0")" && pwd)"
OUT="${DOCS}/screenshots"
CAMERA_PORT="${CAMERA_PORT:-3-4}"
mkdir -p "${OUT}"
gtk4-broadwayd :7 >/dev/null 2>&1 &
BROADWAY=$!
sleep 1
shot() {   # name, fake devices, start page, sub page
	LGHUB_FAKE_DEVICES="$2" GDK_BACKEND=broadway BROADWAY_DISPLAY=:7 \
		timeout 30 python3 "${DOCS}/screenshot.py" "$3" "$4" "${OUT}/$1.png" 2>/dev/null
	echo "$1"
}
shot home 0aaa,c539,c33f,082d home -
shot voice 0aaa voice -
shot effects 0aaa effects -
shot microphone 0aaa microphone -
shot equalizer 0aaa equalizer -
shot mouse c08b device:c08b sensitivity
shot mouse-buttons c08b device:c08b buttons
shot mouse-lighting c08b device:c08b lighting
shot keyboard c33f device:c33f -
shot webcam "082d@${CAMERA_PORT}" device:082d -
kill "${BROADWAY}" 2>/dev/null
