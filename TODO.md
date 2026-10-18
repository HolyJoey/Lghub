# TODO

## Status (2026-10-18)

Lghub covers headsets, mice, keyboards and the rest, receivers and webcams. Tested on this
machine: Blue VO!CE (bit-identical to Windows for all 22 G Pro X presets), the equalizer and
surround (laptop speakers standing in for the headset), webcam settings and preview (laptop
camera). Mice, keyboards and receivers are tested against `simulate.py` only.

| Area | What it is | Logitech's or ours |
| --- | --- | --- |
| Blue VO!CE | DTS MicOpt from G HUB's capture APO, native (`bridge/micopt.c`); G Pro X, G Pro X Wireless, G733 (presets fetched on first sight) | Logitech's DSP and presets |
| Surround | DTS Headphone:X 2.0 from G HUB's HX2E APO, native (`bridge/hx2e.c`) | Logitech's DSP and tunings |
| Equalizer | G HUB's 10-band presets on PipeWire biquads | Logitech's presets, our filters |
| Mice | HID++ 2.0 onboard profiles (0x8100), DPI (0x2201), report rate (0x8060) | the devices' own features |
| Keyboards, other | HID++ 2.0 lighting (0x8070), brightness (0x8040), sidetone (0x8300), battery | the devices' own features |
| Webcams | V4L2 controls and MJPEG preview | standard Linux |
| Pictures, icon | Product photos and the G HUB icon, read from Logitech's depots | Logitech's |

## Check on the real hardware

- **G Pro X**: Automatic picks its mic and output (`pw.is_blue_voice_headset` matches "PRO X";
  confirm the real PipeWire names); its sound card's mixer controls (sidetone?); the PRO_X
  surround tuning by ear; rooms (Entertainment/Gaming/Sports = DLL 0/1/2, from G HUB's enum order).
  The adapter's mic may be stereo or mono; `pw.capture_port` takes MONO, else FL.
- **G502**: profile layout offsets, LED effect bytes (cycle 0x03, breathing 0x0a), report-rate
  byte = ms, writing a 255-byte sector in 16-byte chunks, button order (after Back/Forward the
  names are generic). Backups of every sector written: `~/.local/share/lghub-bluevoice/backups/`.
- **C920**: control names and ranges, preview at 640x360 MJPEG.
- **G733** (not owned, untested): its presets download on first sight; Blue VO!CE picks its mic;
  lighting/battery appear on the Headset page over HID++.
- **Wireless receivers** (simulated only): slots 1-6 answer to a short-report ping; Bolt pairs
  differently and may not.
- **HID++ lighting (0x8070)**: effect parameter bytes and the persist flag; the current effect
  isn't read back (the page starts at the first effect).

## Not done

- Macros and button remaps (in progress): `uinput.py` (virtual keyboard/mouse) and `macros.py`
  (G HUB's macro format: keystroke, text, mouse, media, system, app, web page, audio, sequences)
  are done and tested; the triggers (0x8110 MouseButtonSpy, 0x8010 G-keys, 0x1B04 divert) and
  the UI wait on G HUB's agent code (re/ghub, Ghidra).
- Per-key lighting (0x8080/0x8081): key layout from G HUB's metadata.json; protocol from the agent.
- Keyboard onboard profiles: G HUB's onboard_profiles.proto extracted; format from the agent.
- Yeti: polar pattern, monitor mix, LED meter; protocol from the agent.
- Blue VO!CE 2 (Yetis, G735, PRO X 2; `logi_audio_dts_clearvoice_2_capture_apo.dll`), in
  progress: exported DSP API, parameter struct offsets and the 107 property keys (pid -> field)
  are decoded; G HUB's setting names -> pids come from the agent.
- G HUB's 5-band "PRO" equalizer (pro_eq_presets.json: TSM Bjergsen, Hamlinz, ...): the band
  frequencies aren't in the preset files; the 10-band headset presets are in.

## Could be better

- The background service idles at about 0.2% of one core (was 0.6%): checks now run when a sound
  card or USB device comes or goes, with 60 s fallbacks. What's left is the engine loop and the
  PipeWire link monitor.

## Depot updates

`fetch.py` (APO hashes), `depots.py` (depot paths, the icon's offset and hash) and the two DLL
modules (`micopt.c`, `hx2e.c`: RVAs, checked against the code bytes) are for G HUB 2026.6. A newer
G HUB moves the depots; the code fails cleanly and keeps working without the new files.
