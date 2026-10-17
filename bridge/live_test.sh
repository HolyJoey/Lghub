#!/bin/bash
# End-to-end test of bluevoice-bridge with the default microphone.
set -u
cd "$(dirname "$0")"
export WINEPREFIX=${WINEPREFIX:-$HOME/lghub/wine} WINEDEBUG=-all
HOST=../host
APO='Z:\home\joey\lghub\re\apo_dlls\logi_audio_dts_studio_capture_apo.dll'
cp "$HOST/${1:-broadcaster_1}.params" "$HOST/live.params"
LOG=/tmp/bluevoice_bridge_test.log
OUT=/tmp/bluevoice_from_virtual.wav
rm -f "$LOG" "$OUT"

setsid ./bluevoice-bridge -- wine "$HOST/bluevoice_host.exe" "$APO" "$HOST/live.params" 2> "$LOG" &
BRIDGE=$!
for _ in $(seq 60); do grep -q '^ready' "$LOG" 2>/dev/null && break; sleep 0.5; done
echo "== startup"; grep -v '^meter' "$LOG"
echo "== sources"; wpctl status | sed -n '/Sources:/,/Filters:/p' | head -6

timeout 4 pw-record --target bluevoice_mic --rate 48000 --channels 1 --format f32 "$OUT"
sleep 1
echo "== after recording"; grep -v '^meter' "$LOG" | tail -4
echo "meter lines while recording: $(grep -c '^meter' "$LOG")"
sox "$OUT" -n stat 2>&1 | grep -E "Length|RMS +amplitude|Maximum amplitude"

kill -TERM "$BRIDGE"
wait "$BRIDGE" 2>/dev/null
echo "== shutdown"; tail -2 "$LOG"
