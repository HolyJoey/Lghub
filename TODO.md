# TODO

## Status (2026-10-18)

Working, tested on this machine with the laptop microphone:

- Logitech's Blue VO!CE APO runs under Wine (`host/bluevoice_host.exe`); all 22 G Pro X presets
  verified offline on noisy speech (no NaN / clipping, ~15x realtime); bypass is bit-exact
  pass-through (8 ms APO look-ahead kept in bypass).
- Live virtual microphone (`bridge/bluevoice-bridge`, pw_filter + null-audio node): speech in,
  processed speech out, no drops; underruns only in the first 30 ms after start.
- `engine.py` user service: starts/restarts the bridge, auto-picks a G Pro X (else the default
  mic), relinks on device changes, applies config changes live (crossfaded), default-mic option.
- `app.py`: Voice / Effects / Microphone / My presets pages, live meters, service controls.
- `install.sh` / `uninstall.sh`, `fetch.py` (downloads + verifies Logitech's files).

## Needs the headset

1. **Test with the G Pro X**: check Automatic picks it (`pw.is_pro_x` matches "PRO X" in the
   node name/description — confirm the real name), check levels and that presets sound like
   Windows. The G Pro X USB adapter's mic may be stereo or mono; `pw.capture_port` takes MONO,
   else FL.
2. **G Pro X Wireless**: `fetch.py` already saves `pro_x_wireless_headset_device_presets.json`;
   load those presets when a wireless headset is detected (likely identical).

## Improvements

- **Mic only open while used**: the service keeps the real mic linked (so it's always open while
  Blue VO!CE runs). Try passive links (`pw-link --passive`) plus a shared `node.group`, and check
  the mic still starts when an app records from the virtual mic.
- **Latency**: measure end-to-end (APO 8 ms + host block 10 ms + ring). Possibly smaller host
  blocks (APO accepts any frame count?).
- **Depot updates**: the depot URLs/hashes in `fetch.py` are from G HUB 2026.6. Logitech may
  remove them; add a fallback that finds the current URLs (G HUB's pipeline API is signed
  protobuf — or read `C:\ProgramData\LGHUB\current.json` from an existing G HUB install).
- **Blue VO!CE 2** (newer headsets): `logi_audio_dts_clearvoice_2_capture_apo.dll`, same approach.
- **Packaging**: prebuilt `bluevoice_host.exe` in releases so MinGW isn't required.
- Stream-based virtual sources can't be recorded from on PipeWire 1.4.2 / WirePlumber here (even
  pw-loopback's fail: "no more input formats"); that's why the bridge uses a null-audio node.
