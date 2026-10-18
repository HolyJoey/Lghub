#!/bin/bash
# Renders docs/screenshots/<page>.png without touching the real screen: the app runs on GTK's
# Broadway backend and headless Chromium photographs it. Needs gtk4-broadwayd, chromium and
# ImageMagick, and the app installed (uses live status from the running engine).
set -u
OUT="$(cd "$(dirname "$0")" && pwd)/screenshots"
mkdir -p "$OUT"
DISPLAY_NUM=7
PORT=$((8080 + DISPLAY_NUM))
gtk4-broadwayd ":$DISPLAY_NUM" >/dev/null 2>&1 &
BROADWAY=$!
sleep 1
for page in voice effects microphone presets; do
	GDK_BACKEND=broadway BROADWAY_DISPLAY=":$DISPLAY_NUM" lghub-bluevoice --page "$page" >/dev/null 2>&1 &
	APP=$!
	sleep 4
	chromium --headless=new --disable-gpu --no-sandbox --hide-scrollbars --window-size=1300,1000 \
		--virtual-time-budget=4000 --screenshot="/tmp/bluevoice_$page.png" "http://127.0.0.1:$PORT/" >/dev/null 2>&1
	kill "$APP" 2>/dev/null
	wait "$APP" 2>/dev/null
	# Crop to the window: the bounding box of its dark pixels, plus the rounded corners.
	box=$(magick "/tmp/bluevoice_$page.png" -colorspace gray -threshold 30% -negate -trim -format '%wx%h%O' info:)
	magick "/tmp/bluevoice_$page.png" -crop "$box" +repage "$OUT/$page.png"
	echo "$page: $box"
done
kill "$BROADWAY" 2>/dev/null
