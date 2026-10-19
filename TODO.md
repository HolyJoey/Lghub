# TODO

Only what is still open. What works is in the README; how things were found is in the code's
comments. Checked against the device features G HUB's agent knows (its 212 `Feature####`
classes, G HUB 2026.6) and its app features.

## Progress (overall about 84%)

The percentages are rough estimates of how much of each area's G HUB features Lghub has, not
measurements.

| Area | Done | What's left |
| --- | --- | --- |
| Blue VO!CE (G Pro X, G733) | 100% | check on the G Pro X |
| Blue VO!CE 2 (Yetis, G735) | 95% | check against Logitech's APO under Wine; check on a mic |
| Surround, equalizer | 100% | check on the G Pro X |
| PRO 5-band equalizer | 20% | runs on the headset's Conexant chip (see below); needs the G Pro X |
| Mice | 92% | see "Mice" below |
| Keyboards | 78% | see "Keyboards" below |
| Headsets (other than the voice chain) | 55% | see "Headsets" below |
| Yeti controls | 100% | check on a Yeti |
| Webcams | 90% | check on the C920 |
| Wireless (receivers, power) | 75% | see "Wireless and power" below |
| Lighting | 95% | screen sampler on GNOME / KDE; per-key on mice |
| App features | 85% | see "App" below |
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
  - LIGHTSYNC on its zones (0x8070 fixed colour, not saved) while it is in onboard mode; the
    DPI / profile notices; the tray (clicking a switch)
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
- **0x2240 surface tuning**: done as G HUB's routine (fn 2 / 3, shutter event, fn 4, squal, fn 5,
  event, fn 6; fn 1 sets the three values). Factory surface from fn 0 bytes 6-8, active one found
  by bytes 3-5 (as G HUB). Left: G HUB's hard / soft presets (source not found) and a check on a
  mouse that has it. Lghub reads the movement from the
  mouse's own reports instead of the pointer (ours).
- Left out on purpose: 0x8111 latency monitoring (no setting in G HUB's app), 0x8120 gaming
  attachments (pedals / shifter on racing wheels, not planned).
- Done: 0x2005 left-handed, 0x2400 hybrid tracking, 0x2202 extended DPI, 0x8061 extended report
  rates, 0x80E0 bunny hopping, 0x2240 surface tuning.
- Left out on purpose: 0x2006 pointer orientation, 0x2205 motion scaling and 0x2150 thumbwheel;
  G HUB's agent knows them but its app has no setting for them.
- **Per-key lighting on mice** (if any have it) and 0x8071 inside onboard profiles.

### Keyboards
- **Onboard profiles**: switching the active one works. Editing goes through 0x8102 with the same
  tag protocol as the power timers (done in `device_settings.py`). Found in G HUB: the 0x8102
  functions (0 capabilities, 1 tag list, 6 / 7 read, 9 / 10 write, 11 commit; a profile byte goes
  before the tag) and its tag ids: 0x0003 profile name, 0x0004 key mapping, 0x0100 / 0x0101 report
  rate wired / wireless, 0x0102 game-mode keys, 0x0110-0x0112 base / Fn / G-Shift assignments,
  0x0113 macros, 0x0120-0x0130 analog keys, 0xFF01 profile checksum. Formats found: 0x0003 name =
  32 UTF-16BE characters (64 bytes, zero-padded, "…" at 32 when longer, all 0xFF when empty);
  0x0100 report rate = 1 byte, log2(Hz / 125). fn 6 start read = [profile, tag u16]; fn 9 start
  write = [u16, u16, data]. Left: the other tags' formats, G HUB's v1 / v2 session paths, then a
  keyboard to test.
- **0x8030 MR key** (record a macro on the keyboard): needs the keystrokes, which Lghub can't
  read without input-device access.
- **Analog keyboards**: 0x1B08 / 0x1B0C analog keys, 0x80A3 / 0x80A4 actuation curves.
- **0x1B05 full key customization** (G HUB's "FKC": remap any key, per layer, with presets):
  large; needs a keyboard that has it. Not started.
- 0x4521 game mode on older keyboards done (bits from G HUB, key names from Logitech's HID++
  spec). 0x4523 disable controls (newer keyboards' game mode): fn 0 sets a bitmap of control
  indexes, fn 1 / fn 3 read game-mode bits, fn 2 [0, on | lock << 1] sets game mode (G HUB's
  Feature4523DisableControls); left: which index is which key (the keyboard's control table and
  G HUB's disable_controls_preset.json). 0x8088 multi-lightbar: not started (no device known). Left out: 0x8051 Logi
  modifiers (G HUB uses it inside its key remapping, no setting of its own).
- Left out on purpose: 0x4540 layout, 0x4530 / 0x4531 multi-platform, 0x4220 lock-key state;
  G HUB's app has no setting for them.

### Headsets
- **Centurion (G735, PRO X 2)**: features 0x06xx (mic mute 0x0601, sidetone 0x0604, ANC 0x0605,
  mic gain 0x0611, onboard EQ 0x0636, ...) over G HUB's own transport.
  - Found: messages are HID++ without the device index, with an optional length byte and a
    per-device prefix (CenturionTransport::write 0x14200d030), split into fragments
    (CenturionPacketLayer 0x14200f3c0).
  - Left: the per-device settings from their constructors (`re/notes/decompiled/centurion.c`).
- **Others**:
  - 0x8320 jack detection done (headphone bit ours); 0x8305 bass tone done
  - 0x0200 / 0x0201 / 0x020D volume and EQ sets, 0x020E mic test
  - 0x0800 / 0x0801 / 0x0809 mixer, 0x0900-0x0909 voice processing on the headset
  - 0x0920 Bluetooth EQ
- **Blue VO!CE 2 on the PRO X 2**: no G HUB depot known for it.

### Mics (Yeti)
- 0x8370 mic mute and gain done (G HUB: channel 0, gain x 100, mute flipped on 0AD1 / 0AD2).
- 0x8360 headphone level done (type 2, x 100, the only control G HUB writes).
- 0x8350 mic monitoring done (G HUB's sidetone code: read fn 1 (i, i), write fn 2 (0, 1, level)).
- 0x0B01 iMetering: not a setting; G HUB streams the mic's level readings into its meters with it
  (Lghub's meters come from PipeWire). Nothing to do unless a meter source turns out better.

### Wireless and power
- **Pairing a device to a receiver**: newer LIGHTSPEED receivers pair through 0x1894
  (LightspeedDevicePairing). Found: fn 0 capabilities, fn 1 receiver info, fn 2 open lock (3 bytes,
  meaning not found), fn 3 close lock, fn 4 / 5 pairing info / extended info [slot], fn 6 device
  name [slot], fn 7 unpair [slot]. Left: the open-lock bytes and the pairing events (G HUB's
  AccessoryBus::open_lock_LS2), then a receiver to try it on. Older receivers pair through
  receiver registers.
- **Sleep / power-off timers** (0x8103 GlobalDeviceSettings tags 1 / 2): done with G HUB's tag
  protocol (sessions, tag read / write, CRC-32 commit) and its minute choices. Ours: first data
  bytes in the start-write call. The screen tags (16-19) aren't used (no device with a screen).
- Battery from a voltage (0x1001, 0x1F20 on older wireless headsets): percentages from G HUB's
  battery.xml curves (downloaded at first use). 0x1F20's charging bit is ours; check on a G533 /
  G933.
- 0x0108 AutoSleep (Centurion headsets). 0x1010 charging control done.
- Reconnection: done for devices behind a receiver (the receiver's connection notification wakes
  the restorer at once). Corded devices come through USB hotplug; 0x1D4B (wireless status on
  the device itself) not used.

### Lighting
- **LIGHTSYNC screen sampler**: works on wlroots compositors (grim). GNOME and KDE need Wayland's
  screen-sharing portal and GStreamer's pipewiresrc (permission prompt, PipeWire video stream).
  Keyboards now use G HUB's own regions and key map (screen_sampler-kb.json); its region editor
  is built too (move / resize G HUB's regions; adding new regions isn't).
- Audio visualizer: G HUB's per-key layout and its options (colour mode fixed / reactive /
  gradient, background, boost, max amplitude, noise thresholds, smooth animation; how each shapes
  the level is ours) and the clip zone.
- **Software effects done**: G HUB's own animations (Verticool, Contrastic, Ocean Wave, Lightning,
  Red White and Blue: its keyframe files, downloaded at first use), Starlight, Colour cycle
  and Echo press (key presses read from the keyboard's own reports: ours) with G HUB's settings.
  Not yet: Smooth star / wave (G HUB's players are ~2000 lines of vector maths each; newer
  keyboards only) and G HUB's other "signature" effects. The keyframe editor (Freestyle) is done: frames,
  length, curve, order, preview; saved in G HUB's keyframe format. Effects on zonal devices done
  (starlight, colour cycle, audio, echo press on clicks, screen sampler with G HUB's zone regions). Per-key frames use
  G HUB's single-value call for shared colours; its delta-compressed calls (0x8081 fn 3 / 4) aren't
  used yet: check animation smoothness on a real keyboard first.

### App
- Low-battery notifications done (G HUB's LOW 30 % / CRITICAL 15 %; checking every 5 minutes is
  ours). Game-profile notifications and DPI / profile notices for onboard mice (G HUB's
  OSD_DPI_CHANGED / OSD_PROFILE_CHANGED from 0x8100 events) done. Not yet: G HUB's equalizer /
  surround notices from a headset button. Report-rate notices (0x8061 event) done.
- Game scan done (G HUB scans for installed games): Steam, Heroic / Legendary (Epic), Lutris.
- Tray icon done (G HUB's system tray: devices with battery, Blue VO!CE / equalizer / surround
  switches, Open Lghub; StatusNotifierItem + dbusmenu). config.json "tray": false turns it off.
- Settings page done (G HUB's general settings: notifications, tray, persistent profile). Not
  ours to copy: language (Lghub is English only), analytics, G HUB updates.
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
