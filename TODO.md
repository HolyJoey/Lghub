# TODO

## Status (2026-10-18)

Lghub covers headsets, mice, keyboards and the rest, receivers and webcams. Tested on this
machine: Blue VO!CE (bit-identical to Windows for all 22 G Pro X presets), the equalizer and
surround (laptop speakers standing in for the headset), webcam settings and preview (laptop
camera). Mice, keyboards and receivers are tested against `simulate.py` only.

| Area | What it is | Logitech's or ours |
| --- | --- | --- |
| Blue VO!CE | DTS MicOpt from G HUB's capture APO, native (`bridge/micopt.c`); G Pro X, G Pro X Wireless, G733 (presets fetched on first sight) | Logitech's DSP and presets |
| Blue VO!CE 2 | DTS ClearVoice 2 from G HUB's capture APO, native (`bridge/bv2.c`); Yetis, G735 (presets fetched on first sight) | Logitech's DSP and presets |
| Surround | DTS Headphone:X 2.0 from G HUB's HX2E APO, native (`bridge/hx2e.c`) | Logitech's DSP and tunings |
| Equalizer | G HUB's 10-band presets on PipeWire biquads | Logitech's presets, our filters |
| Mice | HID++ 2.0 onboard profiles (0x8100), DPI (0x2201), report rate (0x8060) | the devices' own features |
| Keyboards, other | HID++ 2.0 lighting (0x8070), per-key (0x8081), brightness (0x8040), sidetone (0x8300), battery | the devices' own features |
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
- **Yeti / G735** (not owned, untested): Automatic picks the mic (`pw.is_bv2_mic` matches
  "yeti", "g735"; confirm the real PipeWire names); Blue VO!CE 2 by ear.
- **G733** (not owned, untested): its presets download on first sight; Blue VO!CE picks its mic;
  lighting/battery appear on the Headset page over HID++.
- **Wireless receivers** (simulated only): slots 1-6 answer to a short-report ping; Bolt pairs
  differently and may not.
- **HID++ lighting (0x8070)**: effect parameter bytes and the persist flag; the current effect
  isn't read back (the page starts at the first effect).

## Progress on the open work (overall about 75%)

| Item | Done | What's left |
| --- | --- | --- |
| DTS room choice | 100% | — |
| Headsets' own EQ presets | 100% | — |
| Background service idle cost | 90% | 0.2% of a core now; the engine loop and the link monitor remain |
| Macros on buttons and G-keys | 90% | DPI/profile actions done; G-Shift; 0x1B04 divert for newer mice; hardware check |
| Per-key lighting | 95% | 0x8081 and 0x8080 done; hardware check |
| Blue VO!CE 2 (Yetis, G735) | 95% | presets, every setting, voice effects, mic gain done; Wine check, hardware check |
| Yeti controls | 50% | polar pattern (0x8330) done; mic monitoring 0x8350, headphone 0x8360, gain/mute 0x8370 over HID++ (gain and headphone volume work through the sound card) |
| Keyboard onboard profiles | 5% | format from G HUB's agent |
| 5-band "PRO" equalizer | 20% | runs on the headset's Conexant chip: write sequence found; HID report layout; G Pro X check |

Details:

- **Macros**: `macros.py` (G HUB's macro format), `uinput.py`, `inputd.py` (0x8110 for mice and
  0x8010 for G-keys, exactly as G HUB's agent drives them: remap entry 0 = handled in software,
  big-endian button mask), Macros page with recorder and "On buttons". DPI up/down/cycle/default/
  shift and profile next/previous/cycle macros run on the mouse (inputd.DeviceActions; how is
  ours: onboard DPI slots and profiles over 0x8100, or 0x2201 in host mode). 0x1B04 (newer
  mice without 0x8110): G HUB's functions found (fn3 SetCtrlIdReporting cid/flags/remap,
  event 0 = up to four pressed control ids) but not its divert flag bits nor its button ->
  control-id map; not done. **Check on the G502**:
  that 0x8110 is there and buttons behave; G-key bit order (G1 = bit 0 of the first byte) on a
  keyboard.
- **Per-key lighting** (0x8081): `perkey_ui.py` draws G HUB's key layout (metadata.json);
  `perkey.py` sends it as G HUB's agent does: SetIndividualRgbZones (fn 1, 4 x zone/r/g/b),
  then FrameEnd (fn 7: persistence, 0, 0). Key -> zone is G HUB's built-in table (keyboard usage
  -3/-0x24/-0x78, G-keys +0xB3, logo +0xD1, indicators +0x98/+0x93, media keys); a device's
  `light_map` resource could override it, none of our depots ships one. Restoring the colours
  when the keyboard connects is ours. 0x8080 (G910/G810/G410) as G HUB drives it: SetKeyColors
  (fn 3: key type bit, count, key/r/g/b x up to 14 in a 64-byte report), Flush (fn 5); key type
  bits from G HUB's firmware_lighting PerKey.Type; which layout group gets which type is per
  device in G HUB's config, ours goes by the names. **Check on a G815/G915 and a G810**: keys
  light where drawn.
- **Blue VO!CE 2** (`logi_audio_dts_clearvoice_2_capture_apo.dll`, fetched at install):
  `bridge/bv2.c` runs the DSP natively, `bluevoice-bridge --engine bv2` around it. G HUB's
  setting names (BlueVoice2.Settings) -> pids from the agent's APO <-> settings code, checked
  against its protobuf offset table. Presets: each device's `defaults_override.json`, fetched
  on first sight (G735, Yeti, Yeti Nano, Yeti X, Yeti X WoW: 11-18 voice presets, 21 effect
  presets). The engine runs Blue VO!CE 2 when the mic is a Yeti or G735. Page: on/off, presets,
  every stage with G HUB's controls and ranges (from its app), voice effects (voice changer,
  chorus, flanger, reverb, delay, ring modulator; enums sent as integers like G HUB). Like G HUB,
  a preset sets every field (0 where its file has none). `inputGain` (the mic's own gain, 0-1)
  goes to the mic's PipeWire volume (wpctl scale, like the Windows slider: ours). Not yet: the
  PRO X 2 (no depot known); a check against the real APO under Wine. Pass-through when off is
  ours.
- **Yeti**: polar pattern 0x8330 done as G HUB drives it (fn0 mask, fn1 get, fn2 set; 1 Stereo,
  2 Cardioid, 3 Bidirectional, 4 Omni). 0x8350 (G HUB's audio::sidetone: mic monitoring level
  and mode), 0x8360 (headphone level), 0x8370 (gain levels, mute = fn3 type 0) have their
  function layouts decoded (re/notes) but the channel numbering isn't pinned down; the sound
  card's own controls cover gain and headphone volume meanwhile. LED meter not done.
- **Keyboard onboard profiles**: G HUB's onboard_profiles.proto extracted; format from the agent.
- **5-band "PRO" equalizer** (pro_eq_presets.json: TSM Bjergsen, Hamlinz, ...): G HUB doesn't
  filter this itself; it sets 5 band gains (+-12 dB) on the headset's own Conexant chip
  (CX2089x, through logi_audio_conexant.dll over HID): the band frequencies live on the chip.
  Decoded so far: the per-band write sequence and gain format; the HID report layout comes
  from a per-chip table still to be read. Needs the G Pro X to check.
- **Service idle**: checks run when a sound card or USB device comes or goes, 60 s fallbacks.

## Compared with G HUB: still missing

Checked against the device features G HUB's agent knows (its `Feature####` classes) and its
app features. Lghub handles 0x0000-0x0005, battery (0x1000/0x1001/0x1004), 0x2201 DPI, 0x8040,
0x8060, 0x8070, 0x8080, 0x8081, 0x8100, 0x8110, 0x8010, 0x8300, 0x8330, 0x2230, 0x40A3,
0x4522, 0x1814,
0x2110/0x2111 and 0x8020. Not yet:

- [ ] Mice: 0x2202 extended DPI and 0x8061 extended report rate (newer mice, 2-8 kHz), 0x1B04
  special keys / divert (newer mice' buttons), 0x2121 hi-res wheel, 0x2130 ratchet wheel,
  0x2240 surface tuning. 0x2230 angle snapping and 0x2110/0x2111 SmartShift done (G HUB's mode
  bytes 1 free spin / 2 ratchet, 0xFF always ratchet, torque; G HUB's speed slider maps to the
  device value with per-model numbers we don't have, so ours shows the device's value 4-50).
- [ ] Keyboards: 0x8071 RGB effects (newer lighting), 0x8030 MR (macro record: needs the
  keystrokes, which Lghub can't read without input-device access), 0x8020 M-keys done (G-key sets
  M1-M3 as in G HUB),
  0x4522 game mode done (the chosen keys stay off: ours, the keyboard can't report them),
  0x1B08 analog keys / 0x80A4 actuation curves (analog keyboards).
- [ ] Headsets: 0x8305 bass tone (functions found, range not), 0x8310 device EQ done (untested,
  no simulator test yet), 0x8320 jack detection, 0x1F20 battery for
  older wireless headsets; the newer "Centurion" protocol (0x06xx: mic mute 0x0601, sidetone
  0x0604, ANC 0x0605, mic gain 0x0611, onboard EQ 0x0636) for G735 / PRO X 2.
- [ ] Mics: 0x8350/0x8360/0x8370 (Yeti, see above); 0x8330 done.
- [ ] Wireless: 0x1815 hosts info, 0x1D4B wireless status, receiver pairing. 0x1814 Easy-Switch
  done (G HUB's fn 0 host count/current, fn 1 switch without waiting for an answer).
- [ ] App features: LIGHTSYNC screen and audio lighting, firmware updates, Discord/OBS
  integrations. Per-game profiles done (profiles.py, Games page: G HUB's Application fields; the
  settings are Blue VO!CE / Blue VO!CE 2, equalizer, surround; how a game is recognised is ours:
  executable name or Steam's AppId=; checked every 5 s while any game is set up).
- [ ] Racing wheels and pedals (0x8123+): G HUB supports them; nobody here owns one.
- [ ] Re-check this list against a newer G HUB now and then (agent strings: `Feature####`).

## Depot updates

`fetch.py` (APO hashes), `depots.py` (depot paths, the icon's offset and hash) and the two DLL
modules (`micopt.c`, `hx2e.c`: RVAs, checked against the code bytes) are for G HUB 2026.6. A newer
G HUB moves the depots; the code fails cleanly and keeps working without the new files.
