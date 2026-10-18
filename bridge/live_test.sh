#!/bin/bash
# End-to-end test of bluevoice-bridge: a known speech clip (or the default mic with --mic)
# -> bluevoice_dsp -> Logitech APO under Wine -> "Blue VO!CE Microphone", recorded back.
set -u
cd "$(dirname "$0")"
export WINEPREFIX=${WINEPREFIX:-$HOME/lghub/wine} WINEDEBUG=-all
# The APO enumerates audio devices during Initialize; Wine's audio drivers make that hang.
export WINEDLLOVERRIDES="winepulse.drv,winealsa.drv,wineoss.drv=d"
HOST=../host
APO='Z:\home\joey\lghub\re\apo_dlls\logi_audio_dts_studio_capture_apo.dll'
PRESET=broadcaster_1
USE_MIC=0
for a in "$@"; do case "$a" in --mic) USE_MIC=1 ;; *) PRESET=$a ;; esac; done
cp "$HOST/$PRESET.params" "$HOST/live.params"
LOG=/tmp/bluevoice_bridge_test.log
OUT=/tmp/bluevoice_from_virtual.wav
rm -f "$LOG" "$OUT"

setsid ./bluevoice-bridge -- wine "$HOST/bluevoice_host.exe" "$APO" "$HOST/live.params" 2> "$LOG" &
BRIDGE=$!
for _ in $(seq 60); do grep -q '^ready' "$LOG" 2>/dev/null && break; sleep 0.5; done
echo "== startup"; grep -v '^meter' "$LOG"

if [ "$USE_MIC" = 1 ]; then
    SRC=$(pw-link -o | grep -m1 "$(wpctl inspect @DEFAULT_AUDIO_SOURCE@ | sed -n 's/.*node.name = "\(.*\)"/\1/p')")
else
    pw-play "$HOST/test/speech48.wav" &
    PLAYER=$!
    for _ in $(seq 20); do SRC=$(pw-link -o | grep -m1 '^pw-play:'); [ -n "$SRC" ] && break; sleep 0.1; done
fi
pw-link "$SRC" bluevoice_dsp:in && echo "linked $SRC -> bluevoice_dsp:in"
pw-link bluevoice_dsp:out bluevoice_mic:input_MONO && echo "linked bluevoice_dsp:out -> bluevoice_mic"

timeout 6 pw-record --target bluevoice_mic "$OUT"
[ "$USE_MIC" = 1 ] || kill "$PLAYER" 2>/dev/null
echo "== bridge"; grep -v '^meter' "$LOG" | tail -3
echo "meter lines: $(grep -c '^meter' "$LOG"), loudest: $(grep '^meter' "$LOG" | sort -k3 -n | tail -1)"
sox "$OUT" -n stat 2>&1 | grep -E "Length|RMS +amplitude|Maximum amplitude"

kill -TERM "$BRIDGE"
wait "$BRIDGE" 2>/dev/null
echo "== shutdown"; tail -2 "$LOG"
