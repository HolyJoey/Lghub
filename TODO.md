# TODO

Only what is still open. What works is in the README; how things were found is in the code's
comments. Checked against the device features G HUB's agent knows (its 212 `Feature####`
classes, G HUB 2026.6) and its app features.

## Progress (overall about 70%)

The percentages are rough estimates of how much of each area's G HUB features Lghub has, not
measurements.

| Area | Done | What's left |
| --- | --- | --- |
| Blue VO!CE (G Pro X, G733) | 100% | check on the G Pro X |
| Blue VO!CE 2 (Yetis, G735) | 95% | check against Logitech's APO under Wine; check on a mic |
| Surround, equalizer | 100% | check on the G Pro X |
| PRO 5-band equalizer | 20% | runs on the headset's Conexant chip (see below); needs the G Pro X |
| Mice | 80% | see "Mice" below |
| Keyboards | 75% | see "Keyboards" below |
| Headsets (other than the voice chain) | 50% | see "Headsets" below |
| Yeti controls | 50% | see "Mics" below |
| Webcams | 90% | check on the C920 |
| Wireless (receivers, power) | 50% | see "Wireless and power" below |
| Lighting | 85% | LIGHTSYNC screen sampler; per-key on mice |
| App features | 70% | see "App" below |
| Background service | 90% | re-measure CPU and memory with the current version installed |

## 1. Check on the real hardware (G Pro X, G502, C920)

Everything below has only met the simulator (`simulate.py`) or the DLLs offline.

- **G Pro X**:
  - Automatic picks its mic and output (`pw.is_blue_voice_headset` matches "PRO X"; confirm
    the real PipeWire names; the mic may be stereo or mono, `pw.capture_port` takes MONO, else FL).
  - Its sound card's mixer controls, the PRO_X surround tuning by ear, rooms (Entertainment /
    Gaming / Sports = DLL 0/1/2 from G HUB's enum order).
  - Then the PRO equalizer (below).
- **G502**:
  - profile layout offsets, LED effect bytes (cycle 0x03, breathing 0x0a)
  - report-rate byte = ms, writing a 255-byte sector in 16-byte chunks, button order
  - 0x8110 software buttons, DPI/profile macros, G-Shift layer
  - Backups of every sector written go to `~/.local/share/lghub-bluevoice/backups/`.
- **C920**: control names and ranges, preview at 640x360 MJPEG.
- **README numbers**: re-measure "Is it heavy?" with the current version installed (new since
  the last measurement: game profiles, the restorer, LIGHTSYNC, Blue VO!CE 2).
- **Untestable here (no device)**:
  - G733, Yetis, G735
  - keyboards: per-key 0x8081 / 0x8080, M-keys, Fn keys, game mode, Easy-Switch names, LIGHTSYNC
  - 0x8071 lighting, SmartShift, the headset EQ 0x8310, receivers
  - Parameter bytes that are ours (not from G HUB) are marked "ours" in the code; those are the
    first suspects.

## 2. Open work, by area

### PRO 5-band equalizer (G Pro X)
G HUB sets 5 band gains (+-12 dB) on the headset's own Conexant chip through
`logi_audio_conexant.dll` (class CxAudioHidDev2089x).
- Found: the per-band write sequence and the gain format.
- Left: the HID report layout from the DLL's per-chip table.
- Plan: read-only first (read the band records), then writes. Notes: `re/notes/proeq.txt`.

### Mice
- **0x1B04 buttons on newer mice** (those without 0x8110): functions found; the divert flag bits
  and G HUB's button -> control-id map not.
- **0x8061 report rates (2-8 kHz)**: functions found; G HUB's rate number -> Hz mapping not.
- **0x2202 extended DPI.**
- **Not started**:
  - 0x2240 surface tuning (a calibration routine on the mouse pad)
  - 0x2006 / 0x2205 pointer orientation and motion scaling (functions found, value ranges not),
    0x2150 thumbwheel (the Linux driver already handles it)
  - 0x80E0 bunny hopping (functions found; whether the byte is the switch or the timeout not),
    0x8111 latency monitoring
  - Done: 0x2005 left-handed, 0x2400 hybrid tracking.
  - 0x8120 gaming attachments
- **Per-key lighting on mice** (if any have it) and 0x8071 inside onboard profiles.

### Keyboards
- **Onboard profiles**: switching the active one works. Editing them needs G HUB's tag format
  (OnboardTagConfigurations, 0x8101/0x8102 profile management) decoded, then a keyboard to test.
- **0x8030 MR key** (record a macro on the keyboard): needs the keystrokes, which Lghub can't
  read without input-device access.
- **Analog keyboards**: 0x1B08 / 0x1B0C analog keys, 0x80A3 / 0x80A4 actuation curves.
- **Not started**:
  - 0x1B05 full key customization, 0x4540 layout, 0x4530 / 0x4531 multi-platform
  - 0x4220 lock-key state, 0x4521 / 0x4523 disable keys / controls (older)
  - 0x8051 Logi modifiers, 0x8088 multi-lightbar

### Headsets
- **Centurion (G735, PRO X 2)**: features 0x06xx (mic mute 0x0601, sidetone 0x0604, ANC 0x0605,
  mic gain 0x0611, onboard EQ 0x0636, ...) over G HUB's own transport.
  - Found: messages are HID++ without the device index, with an optional length byte and a
    per-device prefix (CenturionTransport::write 0x14200d030), split into fragments
    (CenturionPacketLayer 0x14200f3c0).
  - Left: the per-device settings from their constructors (`re/notes/decompiled/centurion.c`).
- **Others**:
  - 0x8320 jack detection (0x8305 bass tone done: G HUB's 0-1 gain x 100)
  - 0x1F20 battery on older wireless headsets
  - 0x0200 / 0x0201 / 0x020D volume and EQ sets, 0x020E mic test
  - 0x0800 / 0x0801 / 0x0809 mixer, 0x0900-0x0909 voice processing on the headset
  - 0x0920 Bluetooth EQ
- **Blue VO!CE 2 on the PRO X 2**: no G HUB depot known for it.

### Mics (Yeti)
- 0x8350 mic monitoring, 0x8360 headphone mix, 0x8370 gain / mute over HID++: function layouts
  decoded; which channel number G HUB passes isn't. (Gain and headphone volume already work
  through the mic's sound card.)
- Yeti LED meter (0x0B01).

### Wireless and power
- **Pairing a device to a receiver**: newer LIGHTSPEED receivers pair through 0x1894
  (LightspeedDevicePairing, async in G HUB: function numbers not read yet); older ones through
  receiver registers.
- **Sleep / power-off timers**: 0x8103 GlobalDeviceSettings is G HUB's tag protocol, shared with
  the 0x8102 onboard profiles (FeatureTagManager):
  - Functions mapped: fn 0 capabilities, fn 1 supported tag list, fn 2 tag capability,
    fn 3 / fn 4 read a tag and its fragments, fn 5 sessions, fn 6 / fn 7 write a tag and its
    fragments, fn 8 commit with a 32-bit check.
  - Tags 1-3 and 16-19 cover power-off / power-saving timeouts and the screen settings.
  - Left: each tag's byte format.
- 0x0108 AutoSleep (Centurion headsets). 0x1010 charging control done.
- Reconnection: Lghub checks every 60 s instead of listening for 0x1D4B (fine for settings;
  not instant).

### Lighting
- **LIGHTSYNC screen sampler**: needs Wayland's screen-sharing portal (permission prompt,
  PipeWire video stream).

### App
- **Firmware updates**: not planned (a mistake can brick a device).
- **Discord / OBS integrations**: not planned.
- **Racing wheels and pedals** (0x8123-0x8140): nobody here owns one.
- **Devices with screens** (0x0A00-0x0A02, 0x8103 Screen..., 0x8130 game data): not started.

## 3. Upkeep

- `fetch.py` (APO hashes), `depots.py` (depot paths, the icon's offset and hash) and the DLL
  modules (`micopt.c`, `hx2e.c`, `bv2.c`: RVAs and export names) are for G HUB 2026.6. A newer
  G HUB moves the depots; the code fails cleanly and keeps working without the new files.
- Re-check this list against a newer G HUB now and then: `Feature####` class names in the
  agent's strings.
