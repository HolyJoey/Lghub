# TODO

## Status (2026-10-18)

Lghub covers headsets, mice, keyboards and the rest, receivers and webcams. Tested on this
machine: Blue VO!CE (bit-identical to Windows for all 22 G Pro X presets), the equalizer and
surround (laptop speakers standing in for the headset), webcam settings and preview (laptop
camera). Mice, keyboards and receivers are tested against `simulate.py` only.

| Area | What it is | Logitech's or ours |
| --- | --- | --- |
| Blue VO!CE | DTS MicOpt from G HUB's capture APO, native (`bridge/micopt.c`) | Logitech's DSP and presets |
| Surround | DTS Headphone:X 2.0 from G HUB's HX2E APO, native (`bridge/hx2e.c`) | Logitech's DSP and tunings |
| Equalizer | G HUB's 10-band presets on PipeWire biquads | Logitech's presets, our filters |
| Mice | HID++ 2.0 onboard profiles (0x8100), DPI (0x2201), report rate (0x8060) | the devices' own features |
| Keyboards, other | HID++ 2.0 lighting (0x8070), brightness (0x8040), sidetone (0x8300), battery | the devices' own features |
| Webcams | V4L2 controls and MJPEG preview | standard Linux |
| Pictures, icon | Product photos and the G HUB icon, read from Logitech's depots | Logitech's |

## Check on the real hardware

- **G Pro X**: Automatic picks its mic and output (`pw.is_blue_voice_headset` matches "PRO X";
  confirm the real PipeWire names); its sound card's mixer controls (sidetone?); the PRO_X
  surround tuning by ear; whether G HUB's "HX2E_GAMING" is DTS room 0 (rooms 0-2 are accepted).
  The adapter's mic may be stereo or mono; `pw.capture_port` takes MONO, else FL.
- **G502**: profile layout offsets, LED effect bytes (cycle 0x03, breathing 0x0a), report-rate
  byte = ms, writing a 255-byte sector in 16-byte chunks, button order (after Back/Forward the
  names are generic). Backups of every sector written: `~/.local/share/lghub-bluevoice/backups/`.
- **C920**: control names and ranges, preview at 640x360 MJPEG.
- **HID++ lighting (0x8070)**: effect parameter bytes and the persist flag; the current effect
  isn't read back (the page starts at the first effect).

## Not done

- DTS room choice in the UI (no names for rooms 1-2 anywhere in Logitech's files).
- Per-key lighting (0x8080/0x8081), G-keys and macros (0x8010, needs a key-remapping daemon),
  keyboard onboard profiles, Yeti's own protocol. Need the hardware to do right.
- Blue VO!CE 2 (newer headsets: `logi_audio_dts_clearvoice_2_capture_apo.dll`), same approach.
- Headsets' own EQ presets: G HUB's headsets point at a preset id that sits in a part of G HUB
  we don't have; the 10-band set comes from the G560 package.

## Depot updates

`fetch.py` (APO hashes), `depots.py` (depot paths, the icon's offset and hash) and the two DLL
modules (`micopt.c`, `hx2e.c`: RVAs, checked against the code bytes) are for G HUB 2026.6. A newer
G HUB moves the depots; the code fails cleanly and keeps working without the new files.
