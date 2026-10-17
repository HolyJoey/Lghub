#!/bin/bash
# Live test: default mic -> Logitech APO (Wine) -> "Blue VO!CE Microphone" virtual source,
# then record from the virtual source to prove audio flows end to end.
set -u
cd "$(dirname "$0")"
export WINEPREFIX=${WINEPREFIX:-$HOME/lghub/wine} WINEDEBUG=-all
APO='Z:\home\joey\lghub\re\apo_dlls\logi_audio_dts_studio_capture_apo.dll'
PARAMS=${1:-broadcaster_1.params}
cp "$PARAMS" live.params
rm -f test/live_host.log test/from_virtual.wav

setsid bash -c "pw-record --raw --rate 48000 --channels 1 --format f32 --latency 10ms - \
  | wine bluevoice_host.exe '$APO' live.params 2> test/live_host.log \
  | pw-play --raw --rate 48000 --channels 1 --format f32 --latency 10ms \
      -P '{ media.class=Audio/Source/Virtual node.name=bluevoice_mic node.description=\"Blue VO!CE Microphone\" audio.position=[MONO] }' -" &
GROUP=$!

for _ in $(seq 60); do grep -q '^ready' test/live_host.log 2>/dev/null && break; sleep 0.5; done
echo "host: $(head -1 test/live_host.log 2>/dev/null)"
sleep 1
timeout 4 pw-record --target bluevoice_mic --rate 48000 --channels 1 --format f32 test/from_virtual.wav
kill -- -"$GROUP" 2>/dev/null
wait "$GROUP" 2>/dev/null
echo "meter lines: $(grep -c '^meter' test/live_host.log)  last: $(grep '^meter' test/live_host.log | tail -1)"
sox test/from_virtual.wav -n stat 2>&1 | grep -E "Length|RMS +amplitude|Maximum amplitude"
