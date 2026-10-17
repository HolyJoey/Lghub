# TODO — paused 2026-10-18 ~00:25

## Where things stand

**Done**
- Found Blue VO!CE 1 (G Pro X): `logi_audio_dts_studio_capture_apo.dll`, a Windows audio
  effect (APO) built on DTS "MicOpt", shipped in G HUB's `driver_audio_apo` depot.
- Mapped all 44 parameters (property keys `{BA8CAF9F-6B5A-4DDE-830B-29E9EAF6E293},pid`, units,
  defaults) from the decompiled DLL — see `docs/apo-parameters.md`.
- Got the 22 G Pro X presets from the `pro_headset` depot (`pro_x_headset_device_presets.json`).
- `host/bluevoice_host.exe` (MinGW, runs under Wine) loads Logitech's real APO and processes
  float32 mono audio on stdin → stdout. Works offline:
  - all 22 presets tested on noisy speech: no NaN / clipping, ~15x realtime
  - live preset switching by rewriting the params file, with 100 ms warm-up + 30 ms crossfade
    (click-free: max jump 0.024 vs 0.48 without)
  - unset parameters fall back to the APO's own defaults (verified byte-identical)
- `bridge/bluevoice-bridge` (native, libpipewire): mic capture stream → host → ring buffer →
  virtual source "Blue VO!CE Microphone". The node appears in PipeWire.

**Broken / unfinished**
1. **Bridge live test fails** — recording from `bluevoice_mic` gets no audio and the source never
   reaches "streaming". Likely causes, in order:
   - stale nodes from earlier test runs were still registered (duplicate `bluevoice_mic`);
     re-test after a clean start (`wineserver -k`, no leftover bridge/host processes)
   - chicken-and-egg: capture is INACTIVE until the virtual mic streams, but the virtual mic
     needs a driver. Options: keep capture always active, or make the source stream
     `PW_STREAM_FLAG_DRIVER` and trigger it, or set `node.group` so both share the mic's driver
   - host never logged `ready` when launched by the bridge — check whether the APO's
     `CoCreateInstance(MMDeviceEnumerator)` makes Wine's audio driver block. Seen a stray
     `bluevoice_host.exe` Stream/Output node in the graph. Fix ideas: `WINEDLLOVERRIDES=winepulse.drv,winealsa.drv=d`
     for the host prefix, or hook/stub the enumerator.
2. **Test with the actual G Pro X** (needs the headset): pick its mic as `--target`.
3. **GTK4/libadwaita app** in the style of `attack-shark-x11`:
   on/off, preset list (22 presets), sliders per stage (HPF, NR, gate, EQ, de-esser,
   compressor, limiter), input-device picker, live in/out meters (host prints `meter in out`
   on stderr every 100 ms), save custom presets.
4. **Background engine**: systemd user service running the bridge from saved config, so
   processing continues with the app closed.
5. **install.sh / uninstall.sh**: create a dedicated minimal Wine prefix (no .NET needed — the
   APO imports only kernel32/user32/advapi32/ole32/oleaut32), download `driver_audio_apo` +
   `pro_headset` depots from `updates.ghub.logitechg.com` (verify SHA-256), extract with
   `tools/depot.py` + `tools/carvepe.py`, build host + bridge, install service + menu entry.
   **Never commit Logitech/DTS files to this repo.**
   Depot URLs currently known (they change with G HUB releases — need a fallback):
   - driver_audio_apo: `.../depots/95ac1553-7dcf-412f-b558-c1e610929c55/driver_audio_apo.depot`
     sha256 `7998b516ee2231d59867a8ae65b4895b7ac06b89ff3492ba20259ac022e97392`
   - pro_headset: `.../depots/6a0e41f1-e878-40e5-a68f-1b004dcccfa3/pro_headset.depot`
6. README with screenshots.

## Fallback if the Wine route stays unreliable
Reimplement the chain natively (LADSPA/LV2 plugin for PipeWire filter-chain) from the
decompiled `dts_micopt_set` logic and compare against the real APO's output on the same input
(offline host gives a reference to match).
