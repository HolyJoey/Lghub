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

## Done since

- Native: no Wine. The DLL's DSP runs in-process; identical to the Windows effect (all 22 presets).
- Mic only open while an app records from Blue VO!CE; ~0% CPU when idle.
- Pro X Wireless preset set; sample-rate changes handled (44.1–192 kHz).

## Needs the headset

1. **Test with the G Pro X**: check Automatic picks it (`pw.is_pro_x` matches "PRO X" in the
   node name/description — confirm the real name), check levels and that presets sound like
   Windows. The G Pro X USB adapter's mic may be stereo or mono; `pw.capture_port` takes MONO,
   else FL.

## Improvements

- **Depot updates**: `fetch.py`'s URLs/hashes are from G HUB 2026.6, and `micopt.c` has two
  offsets specific to this DLL build. A newer DLL needs those offsets re-checked.
- **Blue VO!CE 2** (newer headsets): `logi_audio_dts_clearvoice_2_capture_apo.dll`, same approach.
- Other Blue VO!CE 1 headsets (G733, …): same DLL; only their preset file and device name.
