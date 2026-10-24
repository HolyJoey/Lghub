# Logitech device protocols, as Lghub uses them

What Lghub has worked out about how Logitech G HUB talks to devices, written down so other Linux
projects can use it. Everything here is a description of behaviour in our own words: no G HUB
code, binaries or data files are reproduced. G HUB 2026.6 was the reference.

Most of it has been checked against G HUB's own code and a device simulator, not on every device:
the per-device notes in [TODO.md](../TODO.md) say what has met real hardware.

Notation: `fn n` is HID++ function n of a feature; `[a, b]` are the bytes sent or received after
the HID++ header; multi-byte numbers are big-endian unless noted. **Ours** marks a detail Lghub
chose itself because G HUB doesn't say, or does something else on Windows.

- [HID++ basics](#hid-basics)
- [Mice](#mice)
- [Keyboards](#keyboards)
- [Lighting](#lighting)
- [Headsets and mics](#headsets-and-mics)
- [Wireless, power and battery](#wireless-power-and-battery)
- [Tag protocol (0x8102 / 0x8103)](#tag-protocol-0x8102--0x8103)
- [Centurion (G735, PRO X 2)](#centurion-g735-pro-x-2)
- [G HUB's depots](#g-hubs-depots)
- [G HUB app behaviour](#g-hub-app-behaviour)

## HID++ basics

- A request is a long report: `[0x11, device index, feature index, fn << 4 | software id, params]`.
  Index 0xFF talks to a corded device; 1-6 to devices paired with a receiver.
- Errors come back with feature index 0xFF (HID++ 2.0) or sub id 0x8F (HID++ 1.0).
- Feature 0x0000 (root) gives the index of a feature; 0x0001 lists them.
- Events (notifications) use the same header with software id 0.
- Several programs can read one hidraw node; each gets every report.

## Mice

### Onboard profiles (0x8100)

Profiles live in sectors of the mouse's flash. Sector 0 is the directory; `0x0100 | n` are the
factory profiles (read only). Lghub reads a whole sector, edits it, writes it back in 16-byte
chunks and reads it again to check.

| Offset | Size | Contents |
| --- | --- | --- |
| 0 | 1 | report rate (milliseconds between reports) |
| 1 | 1 | default DPI slot |
| 2 | 1 | DPI-shift slot |
| 3 | 5 × 2 | DPI levels (little-endian, 0 or 0xFFFF = unused) |
| 32 | 16 × 4 | button actions |
| 96 | 16 × 4 | G-Shift button actions |
| 160 | 48 | profile name (UTF-16LE) |
| 208 | 2 × 11 | lighting zones |
| last 2 | 2 | CRC-16/CCITT (init 0xFFFF, poly 0x1021) of everything before it |

Button actions (4 bytes):

| First byte | Meaning |
| --- | --- |
| 0x80 | HID: `[0x80, 0x01, mask hi, mask lo]` mouse buttons (1 left, 2 right, 4 middle, 8 back, 0x10 forward); `[0x80, 0x02, modifiers, usage]` key; `[0x80, 0x03, usage hi, usage lo]` consumer key |
| 0x90 | special: 1 / 2 scroll left / right, 3 DPI up, 4 DPI down, 5 DPI cycle, 6 DPI default, 7 DPI shift, 8 / 9 next / previous profile, 0x0A cycle profiles, 0x0B G-Shift, 0x0C battery level |
| 0x00 | macro |
| 0xFF | disabled (all four bytes 0xFF) |

Lighting zone (11 bytes): effect, then its parameters. Fixed `[0x01, r, g, b, 0]`; breathing
`[0x0A, r, g, b, period u16, 0, brightness]`; colour cycle `[0x03, 0 × 5, period u16, brightness]`;
off `[0x00]`. The same parameter layouts are used by 0x8070 / 0x8071.

Events: 0 = profile activated, 1 = active DPI level changed. G HUB shows an on-screen notice for
both.

### DPI and report rate

- **0x2201** lists DPI values; a word `0xE0nn` means "every nn DPI from the previous value to
  the next".
- **0x2202** (newer mice): fn 1 sensor capabilities (byte 2: bit 0 separate Y DPI, bit 1
  lift-off setting); fn 2 `[sensor, axis, page]` → the same 3 bytes, then 16-bit words (`0xE0nn`
  = step, others DPI values, 0 = end); fn 5 current values `[sensor]` → DPI X, default X, DPI Y,
  default Y, lift-off; fn 6 sets `[sensor, DPI X, DPI Y or 0, lift-off or 0]`. Bit 0 is G HUB's `supports_asymmetric`
  (its XY Split: `Dpi.AdvancedEntry` has `asymmetric`, `dpi_x`, `dpi_y`).
- **0x8060**: report rate in milliseconds.
- **0x8061** (up to 8 kHz): rate numbers 0-6 = 125, 250, 500, 1000, 2000, 4000, 8000 Hz. fn 1 →
  byte 1 is a bitmask of supported rates; fn 2 current; fn 3 set. Event 0 `[connection, rate]`
  when the mouse's own button changes it.

### Other mouse features

| Feature | Functions |
| --- | --- |
| 0x2005 left-handed | fn 0 read, fn 1 set swap |
| 0x2110 / 0x2111 SmartShift | mode 1 free spin, 2 ratchet; auto-disengage 0xFF = always ratchet, else the speed it lets go at; torque (0x2111) from 1 to the device's maximum |
| 0x2230 angle snapping | fn 0 get, fn 1 set |
| 0x2240 surface tuning | see below |
| 0x2400 hybrid tracking | fn 0 engine on?, fn 2 / fn 3 get / set mode (0 low latency, 1 power save) |
| 0x80E0 bunny hopping | fn 1 get, fn 2 set the timeout in 10 ms steps (0 = off, up to 2540 ms); G HUB's slider is 100-1000 ms in 100 ms steps |
| 0x8110 button spy | fn 3 read the remap table, fn 1 start, fn 4 set entries (0 = report in software instead of clicking), fn 2 stop; pressed buttons arrive as a 16-bit mask event |
| 0x1B04 special keys and buttons | fn 0 count, fn 1 `[index]` → control id u16, task id u16, flags (0x20 divertable), position (mouse button n = n); fn 3 `[cid u16, flags, remap u16, flags2]` (G HUB's SetCtrlIdReporting; flags 0x01 divert, 0x02 divert valid, from Logitech's spec); diverted controls held arrive as event 0, up to four control ids. Newer mice without 0x8110 get button macros this way |

**Surface tuning (0x2240)**, G HUB's sequence:

1. fn 2, then fn 3: start.
2. The user moves the mouse. One unit is 200 counts; G HUB wants 4-18 units per second.
3. After 20 units the mouse sends event 0 `[status, LED drive]` (status 0 = done). fn 4 starts
   the surface-quality step.
4. After 65 more units fn 5 stops it; event 1 `[status, pixel threshold, minimum surface quality]`.
5. fn 6 ends tuning (also when cancelled).

fn 1 writes the three values `[LED drive, pixel threshold, minimum quality]`. fn 0 reports the
values in use (bytes 3-5) and the factory ones (bytes 6-8). **Ours:** Lghub measures the movement
from the mouse's own HID reports rather than the pointer.

## Keyboards

| Feature | Functions |
| --- | --- |
| 0x4521 disable keys (older) | five fixed keys, one bit each: fn 0 available, fn 1 off now, fn 2 set. Bit names from Logitech's spec: Caps Lock, Num Lock, Scroll Lock, Insert, Windows |
| 0x4522 disable keys by usage | fn 0 how many, fn 1 turn these HID usages off, fn 2 back on, fn 3 all on |
| 0x4523 disable controls (newer) | fn 0 bitmap of control indexes; fn 1 / fn 3 read the game-mode bits; fn 2 `[0, on \| lock << 1]`. G HUB's presets list control ids (CIDs) from the key pictures; which index is which key comes from the keyboard |
| 0x40A3 Fn inversion | fn 0 `[host]` → state, default, capabilities; fn 1 set |
| 0x1B08 analog keys | G HUB's Feature1B08AnalogKeys: fn 0 capabilities, fn 1 / fn 2 get / set rapid trigger, fn 3 key-travel events, fn 4 / fn 5 get / set key priority; a set is one byte, bit 0 = on (that a get answers in bit 0 is ours). Actuation points and rapid-trigger sensitivity per key are in the onboard profile (tags 0x0120-0x0130) |
| 0x1990 illumination light (Litra) | G HUB's Feature1990IlluminationLight: fn 0 / fn 1 get / set on (1 byte), fn 2 brightness info `[flags, minimum u16, maximum u16, step u16, levels]` (that the third is the step is ours), fn 3 / fn 4 get / set brightness (u16, lumens), fn 7 colour-temperature info (same layout), fn 8 / fn 9 get / set colour temperature (u16, kelvin), fn 12 the effective maximum brightness |
| 0x8010 G-keys | fn 2 `[1]` = report G-keys to software; events carry a bitmask (G1 = bit 0 of byte 0) |
| 0x8020 M-keys | event 0 = M-key pressed; fn 1 lights them (M1 = 1, M2 = 2, M3 = 4) |
| 0x8040 brightness | fn 0 info (maximum, u16), fn 1 get, fn 2 set (u16) |
| 0x1814 / 0x1815 Easy-Switch | 0x1814 fn 0 host count and current, fn 1 switch (no answer: the device leaves); 0x1815 host names in 14-byte pieces |

**Onboard profiles on keyboards (0x8102)** use the [tag protocol](#tag-protocol-0x8102--0x8103):
fn 0 capabilities, fn 1 tag list, fn 6 / fn 7 read, fn 9 / fn 10 write, fn 11 commit; a profile
byte comes before the tag. Tag ids G HUB uses:

| Tag | Contents |
| --- | --- |
| 0x0003 | profile name: 32 UTF-16BE characters, 64 bytes, zero-padded; all 0xFF when empty |
| 0x0004 | key mapping |
| 0x0100 / 0x0101 | report rate wired / wireless: 1 byte, log2(Hz / 125) |
| 0x0102 | game-mode keys |
| 0x0110-0x0112 | base / Fn / G-Shift layer assignments |
| 0x0113 | macros |
| 0x0120-0x0130 | analog keys |
| 0xFF01 | profile checksum |

Other tags' formats are still unknown.

## Lighting

### Zones (0x8070 / 0x8071)

- **0x8070**: fn 0 zone count; fn 1 `[zone]` → `[zone, location u16, effect count]`; fn 2
  `[zone, effect]` → `[?, effect id u16]`; fn 3 `[zone, effect index, 10 parameter bytes,
  persist]`.
- **0x8071**: fn 0 `[0xFF, 0xFF, 0]` → cluster count at byte 2; `[cluster, 0xFF, 0]` → location
  (bytes 2-3) and effect count (byte 4); `[cluster, effect, 0]` → effect id (bytes 2-3). fn 1
  `[cluster, effect index, parameters, persist]` (**ours:** that it takes 0x8070's parameter
  bytes and persist flag).
- HID++ effect ids, as G HUB's feature_8070 / feature_8071_lighting_effects read them (the
  same for both): 0 off, 1 fixed, 3 colour cycle, 4 colour wave, 10 breathing, 11 ripple,
  12 custom, 13 KITT, 14 colour blend, 15 / 16 signature (keyframes, active / idle), 17 Pulsar
  Point, 18 Neutron Null, 19 streaming, 21-23 smooth colour cycle / colour wave / ripple,
  24 / 25 signature (algorithmic, active / idle), 26 / 27 signature (built in), 28 key travel
  glow. 2 "pulse" isn't in G HUB's list (ours). G HUB's Smooth Star / Smooth Wave have no HID++
  id: they are software effects.
- Parameters (10 bytes, G HUB's get_raw_effect_params): fixed `[r, g, b, 2]`; breathing
  `[r, g, b, period u16, 0, brightness]`; colour cycle and signature 15 / 16
  `[0 × 5, period u16, brightness]`; colour wave `[0 × 6, period low, direction (1-8), brightness,
  period high]`; ripple `[r, g, b, ?, period u16]`; two colours (17, 18, 24, 25)
  `[r, g, b, r2, g2, b2, period u16, intensity %, style]`, style = G HUB's signature effect index
  (0 IMMERSE, 1 Pulsar Point, 2 G3 Signature, 3 Reminds Me Of, 4 Neon, 5 Outer Space); key
  travel glow `[r, g, b, r2, g2, b2, %, %]`. Brightness and intensity are percentages, at least 1.
  Ours: the two-colour period stays at G HUB's default 50 ms (the G515's defaults_override.json);
  what the period means for them isn't known.

### Per-key (0x8081, 0x8080)

- **0x8081**: fn 1 SetIndividualRgbZones `[zone, r, g, b] × 4`; fn 2 SetConsecutiveRgbZones
  `[first zone, (r, g, b) × up to 5]`; fn 3 / fn 4 SetConsecutiveRgbZonesDeltaCompression 5-bit /
  4-bit (16 bytes packed by G HUB's caller, packing not found); fn 5 SetRangeRgbZones
  `[first zone, last zone, r, g, b] × up to 3`; fn 6 SetRgbZonesSingleValue
  `[r, g, b, up to 13 zone ids]`; fn 7 FrameEnd `[persistence, 0, 0, 0, 0]` (G HUB's
  Feature8081PerKeyLighting senders). Lghub uses fn 1, 6 and 7. G HUB turns each key of its
  layout into a zone number with a built-in table.
- **0x8080** (G910, G810, G410): fn 0 info (bytes 0-1: key types as bits); fn 3 SetKeyColors
  `[type u16, count u16, (key, r, g, b) × up to 14]`; fn 5 flush. Types: keyboard 1,
  consumer 2, G-key 4, button 8, logo 0x10, other keys 0x40.

### Light maps and device effects (newer depots)

- **light_map.json** (newer keyboards, the G502 X PLUS): `perKey` → PerKey type → `mapping`
  `{id: {"ledIndex": n}}`; it overrides the default key → zone table for the keys it lists (the
  PRO X TKL moves its media keys: Play/Pause 205 → 152, the table says 155).
- **metadata.json** LEDs on mice are `circle` renderings: `rect: {x, y, r}` (centre and radius).
- **lighting_effects.json** (G502 X PLUS): `effects: [{name, keyframeInfo}]`, the same keyframe
  format as the core depot's effects; SIGNATURE_FRAME_ACTIVE / _INACTIVE on PERKEY_COSMETIC.

### Software effects (what G HUB's player does)

- **Keyframe animations** (G HUB's prefab effects and Freestyle): a list of frames, each with a
  length, an easing curve into it and a colour per key. A frame lasts `length × speed`
  milliseconds. Directions: cycle, reverse, bounce, random. The 41 easing curves are Qt's
  QEasingCurve set (linear, in / out / in-out / out-in × quad, cubic, quart, quint, sine, expo,
  circ, elastic, back, bounce), plus "none" (jump).
- **Starlight**: "star count" is how many stars are lit at once. Each star fades in over the
  speed time, then out. Star count 5-100, speed 100-10000 ms.
- **Colour cycle**: a transition over the speed time, then a hold for the delay. Speed
  1000-10000 ms.
- **Screen sampler**: G HUB's regions are insets from each screen edge (left, top, right,
  bottom as 0-1 fractions); each key or zone names its region. A new region in G HUB's editor
  starts 0.4 in from every edge. When a region is deleted, its keys get the tag
  `BACKGROUND_COLOR`. Colour boost 0-3, shown as 0-100 %.
- **Audio visualizer**: G HUB's per-key layout is 57 columns, each a frequency range with its
  keys from bottom to top. Options: colour mode fixed / reactive / gradient, background colour,
  boost, adaptive or fixed maximum amplitude, bass and mid / high noise thresholds, smooth
  animation, clip zone (threshold and colour); sliders 0-100 %.

## Headsets and mics

| Feature | Functions |
| --- | --- |
| 0x8300 sidetone | fn 0 get level (0-100), fn 1 set |
| 0x8305 bass tone | fn 0 get, fn 1 set 0-100 |
| 0x8310 equalizer | fn 0 info (band count, dB range, capabilities, min, max); fn 1 `[band index]` → 16-bit frequencies; fn 2 gains (signed dB, one byte each); fn 3 set `[2, gains...]`; fn 4 / fn 5 get / set on |
| 0x8320 jack detection | fn 0 → `[jacks in use, jacks present]`, one bit per jack |
| 0x8330 polar pattern (Yetis) | fn 0 bitmask (bit n = pattern n + 1), fn 1 current, fn 2 set; event 0 on change |
| 0x8350 mic monitoring (Yetis) | fn 1 `[i, i]` → `[?, ?, active, level]`; fn 2 `[0, 1, level]` |
| 0x8360 headphone level (Yetis) | as 0x8370; type 2 = level |
| 0x8370 mic gain and mute (Yetis) | fn 0 channels; fn 2 `[channel, control]` → `[?, ?, type, value]`; fn 3 `[channel, type, value]`. Types: 0 mute, 1 / 2 gain, 5 an unused switch. Channel 0. Mute is inverted on USB ids 0AD1 / 0AD2 |

Levels are G HUB's 0-1 values × 100.

## Wireless, power and battery

- **Pairing** (G HUB's HPP10Command): HID++ 1.0 set register 0xB2 on the receiver (index 0xFF):
  `10 FF 80 B2 01 00 00` opens the lock on LS1 receivers, `… 07 …` on LS2, `… 02 …` closes it. A
  device that pairs sends the connection notice 0x41; the lock state comes as 0x4A (bit 0 = open).
- **Bluetooth** (ours, not from G HUB): Logitech devices connected over Bluetooth are HID devices
  on bus 0005 (`/sys/bus/hid/devices/0005:046D:<pid>.*`); their hidraw node takes HID++ with
  device index 0xFF, as a corded device does. G HUB lists the Bluetooth product ids (046d:bxxx).

- **Battery**: 0x1004 fn 1 and 0x1000 fn 0 → `[percent, ?, state]`. States: 0 on battery,
  1 charging, 2 almost full, 3 charged, 4 charging slowly.
- **Voltage**: 0x1001 fn 0 → `[millivolts u16, flags]` (0x80 = charging). 0x1F20 fn 0
  `[channel]` → `[millivolts u16, flags]` on older wireless headsets.
- **Percent from voltage**: G HUB uses each device's `battery.xml` from its depot. It holds a
  discharge curve (time, voltage, capacity used) and a charging curve (voltage, state of
  charge).
- **0x1010 charging control**: fn 0 get, fn 1 set on / off.
- **Receiver connection notice**: HID++ 1.0 report sub id 0x41; bit 6 of the flags byte set =
  link not established. G HUB re-applies settings when it arrives.
- **0x1894 LIGHTSPEED pairing** (newer receivers):
  - fn 0 capabilities, fn 1 receiver info.
  - fn 2 open lock (3 bytes, meaning unknown), fn 3 close lock.
  - fn 4 / fn 5 `[slot]` → pairing info / extended info.
  - fn 6 `[slot]` → device name.
  - fn 7 `[slot]` unpair.
- **0x1B04 special keys**: fn 1 control info, fn 2 `[cid]` → reporting, fn 3 `[cid hi, cid lo,
  flags, remap hi, remap lo, extra]` sets it.
- **Power timers**: 0x8103 tags 1 (power saving) and 2 (power off), seconds as u16. G HUB's
  choices in minutes: power saving Never / 1 / 2 / 5 / 10 / 15, power off Never / 1 / 2 / 5 /
  10 / 15 / 30 (Never / 5 / 15 / 30 / 60 on mice without the advanced timer). Never = 0.

## Tag protocol (0x8102 / 0x8103)

Shared by 0x8103 (global device settings) and 0x8102 (keyboard onboard profiles, with a profile
byte before each tag).

1. **Session**: fn 5 `[operation]`, START = 0, END = 3. Reads and writes happen inside one
   session.
2. **Read**: fn 3 `[tag u16]` → `[sequence, length u16]`; then fn 4 `[sequence]` →
   `[sequence, 15 data bytes]` until `length` bytes are in.
3. **Write**: fn 6 `[tag u16, size u16, first data bytes]`; fn 7 `[sequence, 15 bytes]` for the
   rest; fn 8 commit `[CRC-32 of the data, u32]` → `[status, ...]`, 0 = written. The CRC is the
   standard zlib CRC-32.

**Ours:** how many data bytes ride in the fn 6 call.

## Centurion (G735, PRO X 2)

Newer headsets use features in the 0x06xx range over G HUB's own Centurion transport instead of
plain HID++: 0x0601 mic mute, 0x0604 sidetone, 0x0605 noise cancelling, 0x0611 mic gain, 0x0636
onboard equalizer, and others.

- Messages are HID++-like without the device index, with an optional length byte and a
  per-device prefix, split into fragments.
- They go over the HID collection G HUB calls the "Avnera Centurion collection".
- Devices behind a 0x0003 bridge go through a sub-device layer that refuses packets larger than
  the adapter's size.

Not implemented in Lghub yet.

## G HUB's depots

G HUB downloads its data from `https://updates.ghub.logitechg.com/depots/<uuid>/<name>.depot`.

- **Format**: `[magic 0x20170110 u32 LE, header length u32 LE, header JSON]`. The header has a
  `files` list. Each file follows as a u32 LE length, then its bytes, so HTTP range requests
  can fetch a single file. A length of 0xFFFFFFFF is taken to mean a u64 length follows (ours:
  no file that large has been seen).
- **Encrypted depots (capsules)**: magic 0x20210506, a header `{"header-sha", "key-id"}`, then a
  u32 length and the encrypted file list (`files`: name, mode, sha), then the files as above,
  each encrypted. Every part is AES-128-GCM under the key named `key-id`, with the IV
  PBKDF2-HMAC-SHA512(the part's SHA-256 as hex, `key-id`, 1000 rounds, 32 bytes); the SHA-256 is
  of the decrypted bytes, so it checks the result. Some files in a capsule (larger pictures) are
  **sealed files**: magic 0x20210521, header `{"key-id", "file-sha"}`, u32 length, payload,
  encrypted the same way; the capsule's hash is then that of the file within. G HUB's own
  device lists (`data/devices/*.json` in the core depot) are sealed files too.
- **Keys**: G HUB's update channel (`pipeline/v2/update/ghub13/win/public/details.json` on the same
  host) lists the depots and names an access group; `pipeline/v2/access/<group>/content.json`
  lists the keys (name = key id, base64 AES key). Lghub fetches them the first time it needs one.
- **Useful files**:
  - Core depot, `LGHUB/data/lighting/`: `effect_prefabs.json`, `effects/*.json` (the keyframe
    animations, screen sampler regions and the visualizer layout).
  - Per device: `metadata.json` (key layout and pictures), `battery.xml` (battery curves),
    `manifest.json`.

## G HUB app behaviour

- **Notifications**:
  - Battery low at 30 %, critical at 15 %.
  - On-screen notices for DPI, profile and report-rate changes, equalizer cycling, surround on /
    off, and audio input / output changes.
- **Button actions** G HUB offers beyond plain keys: DPI up / down / cycle / default / shift,
  profile cycle, G-Shift, report-rate cycle, battery level, mute mic / speakers, volume, mic gain,
  sidetone, bass and treble up / down, equalizer cycle, advanced equalizer toggle, surround
  toggle, audio output / input cycle, media keys, wheel actions.

### PRO equalizer (G Pro X's Conexant chip, `logi_audio_conexant.dll`)

- CxAudioHidDev2089x = chip table entry 5 ("ANDRUS"). Memory space 1 (read / write,
  0x0000-0x27FF): request report 4 `[4, flags, length ≤ 32, address high, address low, data…]`
  (flags 0x40 write, 0x10 address above 0xFFFF), padded to the output report; reply report 5
  `[5, data…]`. Protocol variant 1, no checksum.
- Register 0x1152 (low 2 bits) = active EQ profile; command 0x1154 applies a change.
- Band records: 5 × 11 bytes per profile at `profile × 0x37 + 0xFE9` (band 1 first): signed
  16-bit b0, b1, b2, −a1, −a2 and a shift byte s, each word × 2^−(15 − (s − 2)); gains are
  dB × 256 in G HUB's band parameters.
