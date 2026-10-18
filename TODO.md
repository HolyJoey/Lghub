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

## Multi-device (full G HUB replacement)

- [x] Home screen: connected devices from sysfs (polled every 2 s), our own model table in
  `devices.py` (USB ids, lighting zones, onboard profiles, battery), per-device pages.
  The G Pro X (wired/wireless) opens Blue VO!CE; Blue VO!CE also has its own tile.
  Test without hardware: `LGHUB_FAKE_DEVICES=0aaa,c08b,082d lghub`.
- [x] Mice (G502): DPI, report rate, buttons, onboard profiles, lighting (HID++ 2.0:
  0x2201, 0x8060, 0x8100), tested against `simulate.py` only (`python3 -m unittest discover tests`).
  **Check on the real G502**: profile layout offsets, LED effect bytes (cycle 0x03, breathing
  0x0a), report-rate byte = ms, the write of a 255-byte sector in 16-byte chunks, button order
  (names after Back/Forward are generic "Button n"). Backups of every sector we write are in
  `~/.local/share/lghub-bluevoice/backups/<serial>/`.
- [x] G Pro X extras: 10-band equalizer (our own PipeWire filter-chain, run by the engine,
  live gains), Headset page (the headset sound card's ALSA controls: sidetone, mic level,
  volume; plus HID++ sidetone 0x8300 if the adapter has it). **Check on the real G Pro X**:
  which mixer controls its card has; that Automatic finds its sink (`pw.is_pro_x`).
- [ ] DTS Headphone:X surround: Logitech's render APOs only export COM; needs a COM host for
  `logi_audio_headset_render_apo.dll` (like the Blue VO!CE bridge, but for playback). Not
  started.
- [x] Webcams (C920): every V4L2 control, grouped (picture, white balance, exposure, focus
  and zoom); saved per camera and restored by the engine on plug-in. Tested on the laptop's
  own camera (`LGHUB_FAKE_DEVICES=082d@3-4`). No live preview yet.
- [ ] Keyboards and the rest; receivers (devices paired to LIGHTSPEED/Unifying).
- [ ] Product images, downloaded at install time.

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
