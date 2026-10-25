# TODO

Only what is still open. What works is in the README; how things were found is in the code's
comments. Checked against the device features G HUB's agent knows (its 212 `Feature####`
classes, G HUB 2026.6) and its app features.

## Check first: G Pro X headset (mic, Blue VO!CE, surround)

- Sidetone slider is missing. G HUB sets sidetone only over HID++ (0x8300; 0x0604 on Centurion),
  never through the sound card. Since 0.9.8 the page says why there's no slider (HID++ didn't
  answer, or the headset doesn't report 0x8300): read that on the PC, and the user's own sidetone
  script there.
- Surround was silent: fixed in 0.9.8. The DSP's inputs stalled after one buffer when linked
  before its outputs (PipeWire 1.4.2, measured with a test tone into a null sink); the engine now
  links DSP -> headset first. Check by ear on the G Pro X.
- Versions: 0.9.8's updater reads four-part versions, so small fixes can ship as 0.9.8.x
  (0.9.7 and older only see three-part ones).

## Progress (overall about 85%)

The percentages are rough estimates of how much of each area's G HUB features Lghub has, not
measurements.

| Area | Done | What's left |
| --- | --- | --- |
| Blue VO!CE (G Pro X, G733) | 100% | check on the G Pro X |
| Blue VO!CE 2 (Yetis, G735, PRO X 2) | 95% | check against Logitech's APO under Wine; check on a mic |
| Surround, equalizer | 100% | check on the G Pro X |
| PRO 5-band equalizer | 95% | done with G HUB's own band maths (its DLL, run natively) and its busy check; check on the G Pro X |
| Mice | 94% | see "Mice" below |
| Keyboards | 80% | analog keys' per-key settings and onboard-profile editing (formats found, not built); see "Keyboards" below |
| Headsets (other than the voice chain) | 60% | Centurion transport and sidetone done; its other features; see "Headsets" below |
| Yeti controls | 100% | check on a Yeti |
| Litra lights | 90% | check on a Litra Glow / Beam |
| Webcams | 90% | check on the C920 |
| Wireless (receivers, Bluetooth, power) | 80% | pairing; see "Wireless and power" below |
| Device catalog | 100% | 11 of G HUB's device files have keys outside its public channel (unreleased?) |
| Lighting | 97% | signature effects' zonal versions, G Tide's key-list ids (rings are ours for now); screen sampler portal on GNOME / KDE |
| App features | 85% | see "App" below |
| Background service | 95% | re-measured 2026-10-20: 0.2% CPU, 28 MB idle |

## 0. Status (2026-10-20)

The small high-value items are done: update button (tested 0.9.0 -> 0.9.1), receiver pairing,
receiver ids, screenshots, scans, Litra lights (0x1990). The G502 X "no photo" seen in a screenshot wasn't a bug: its
photo (5 MB, encrypted twice) takes a few seconds the first time, and the screenshot was taken
before it arrived; the tile updates when it does. From here: fix what testers report.

## 1. Check on the real hardware (G Pro X, G502, C920, newer models)

Everything below has only met the simulator (`simulate.py`) or the DLLs offline.

- **G Pro X**:
  - Automatic picks its mic and output (`pw.is_blue_voice_headset` matches "PRO X"; confirm
    the real PipeWire names; the mic may be stereo or mono, `pw.capture_port` takes MONO, else FL).
  - Its sound card's mixer controls, the PRO_X surround tuning by ear, rooms (Entertainment /
    Gaming / Sports = DLL 0/1/2 from G HUB's enum order).
  - Then the PRO equalizer (below).
- **Bluetooth** (found as `0005:046D:*` HID devices, ours): a G604 / G915 over Bluetooth shows
  up, its page talks HID++ (device index 0xFF), battery in the tray, the new udev line.
- **Newer models** (from G HUB's device list): a G502 X / PRO X SUPERLIGHT 2 / G515 shows up with
  its picture; analog keyboards' rapid trigger and key priority switches (0x1B08) on a real one.
- **Litra** (0x1990, from G HUB's Feature1990IlluminationLight): on / off, brightness and colour
  temperature on a real Litra Glow / Beam; that the third u16 of the info replies is the step is ours.
- **G502**:
  - profile layout offsets, LED effect bytes (cycle 0x03, breathing 0x0a)
  - LIGHTSYNC on its zones (0x8070 fixed colour, not saved) while it is in onboard mode; the
    DPI / profile notices; the tray (clicking a switch)
  - report-rate byte = ms, writing a 255-byte sector in 16-byte chunks, button order
  - 0x8110 software buttons, DPI/profile macros, G-Shift layer
  - Backups of every sector written go to `~/.local/share/lghub/backups/`.
- **C920**: control names and ranges, preview at 640x360 MJPEG.
- **Untestable here (no device)**:
  - G733, Yetis, G735
  - keyboards: per-key 0x8081 / 0x8080, M-keys, Fn keys, game mode, Easy-Switch names, LIGHTSYNC
  - 0x8071 lighting, SmartShift, the headset EQ 0x8310, receivers
  - Parameter bytes that are ours (not from G HUB) are marked "ours" in the code; those are the
    first suspects.

## 2. Open work, by area

### PRO 5-band equalizer (G Pro X)
Done: the PRO equalizer card on the G Pro X's headset page (profiles 1-4, five bands +-12 dB with
their type and frequency). It talks to the headset's Conexant chip as G HUB does (memory reads /
writes over report 4 / 5, then the apply bit), and G HUB's own band design and analysis run from
its logi_audio_conexant.dll (pinned build, fetched at first use) through bin/proeq-design.
Done too: G HUB's busy check before writes (FUN_18000e180). Left: taking frequency / Q from the chip's EEPROM
copy instead of the band record (same values). Notes: `re/notes/proeq.txt`.

### Mice
- **0x1B04 buttons on newer mice** (those without 0x8110, like the G502 X): done: macros on
  buttons divert the buttons' controls (G HUB's 6-byte SetCtrlIdReporting; flag bits from
  Logitech's spec; G HUB's SetCtrlIdReportingAsync only packs its caller's bytes, caller not found) and read the diverted-controls events. Check on a
  G502 X. Not needed: remapping a button to another button's job (fn 3's remap field); these
  mice keep their buttons' jobs in the onboard profile, which the Buttons page edits.
- **0x2240 surface tuning**: done as G HUB's routine (fn 2 / 3, shutter event, fn 4, squal, fn 5,
  event, fn 6; fn 1 sets the three values). Factory surface from fn 0 bytes 6-8, active one found
  by bytes 3-5 (as G HUB). G HUB's PRESET_HARD / PRESET_SOFT surface types exist in its protocol but
  nothing in G HUB 2026.6 creates them (surface_tuning_control 0x1417f9fc0 builds the factory
  surface and custom ones only), so there is nothing to copy. Left: a check on a mouse that has it. Lghub reads the movement from the
  mouse's own reports instead of the pointer (ours).
- Left out on purpose: 0x8111 latency monitoring (no setting in G HUB's app), 0x8120 gaming
  attachments (pedals / shifter on racing wheels, not planned).
- Done: 0x2005 left-handed, 0x2400 hybrid tracking, 0x2202 extended DPI, 0x8061 extended report
  rates, 0x80E0 bunny hopping, 0x2240 surface tuning.
- Left out on purpose: 0x2006 pointer orientation, 0x2205 motion scaling and 0x2150 thumbwheel;
  G HUB's agent knows them but its app has no setting for them.
- **Per-LED lighting on mice**: done for the G502 X PLUS (and its Millennium Falcon edition): a
  Light strip page from G HUB's layout (its LEDs are circles there), sent over 0x8081 through the
  model's light_map.json, with its signature effects (lighting_effects.json: keyframe animations,
  played by softlight). Check on the mouse. Left: 0x8071 inside onboard profiles.
- **Battery time left** (newer models' battery.xml are power models: capacity in Wh, milliwatts
  per sensor / MCU / roller / report rate / lighting effect): done as G HUB's agent does it
  (hours = percent / 100 * Wh * 1000 / mW, its max_life_span and "mileage"). Ours: the running
  lighting effect isn't read back, so it shows a range from solid at full brightness to off;
  the nearest report-rate interval when there's no exact one. Check against G HUB on a G502 X
  PLUS / PRO X SUPERLIGHT 2 (the files give 137 h / 92 h; Logitech says 130 h / 95 h).
- **G HUB's sensitivity presets** (MOUSE_SETTINGS_ADVANCED in defaults_override.json: Default,
  First Person, Third Person, MMORPG, MOBA, RTS, Simulation, Productivity, pro players' ones):
  done on onboard mice' Sensitivity page ("Use" puts them in the profile). Left out: the "XY
  Split" ones (separate X / Y DPI; our known profile layout has one per level). XY Split itself
  is done for live DPI (0x2202 caps bit 0, G HUB's supports_asymmetric) on mice without onboard
  memory; whether newer mice' profiles hold a Y DPI isn't known.

### Keyboards
- **Onboard profiles**: switching the active one works. Editing goes through 0x8102 with the same
  tag protocol as the power timers (done in `device_settings.py`). Found in G HUB: the 0x8102
  functions (0 capabilities, 1 tag list, 6 / 7 read, 9 / 10 write, 11 commit; a profile byte goes
  before the tag) and its tag ids: 0x0003 profile name, 0x0004 key mapping, 0x0100 / 0x0101 report
  rate wired / wireless, 0x0102 game-mode keys, 0x0110-0x0112 base / Fn / G-Shift assignments,
  0x0113 macros, 0x0120-0x0130 analog keys, 0xFF01 profile checksum. Formats found: 0x0003 name =
  32 UTF-16BE characters (64 bytes, zero-padded, "…" at 32 when longer, all 0xFF when empty);
  0x0100 report rate = 1 byte, log2(Hz / 125). fn 6 start read = [profile, tag u16]; fn 9 start
  write = [u16, u16, data]. Found 2026-10-24 (re/notes/keyboard_profiles.txt): the base layer tag 0x110
  holds per-key "FKC" rows (5 x u16: opCode, actionBitfield, params, ...) and analog "MA" groups;
  G HUB's opcodes: 0x8002 key (+ modifiers), 0x8000 modifiers only, 0x8001 mouse button bitmask,
  0x8003 media usage, 0x9001-0x9007 wheel / DPI, 0x9008-0x900A / 0x900C / 0x9017 profile, battery,
  report rate. Macro steps (MACROS_LIBRARY) found too: delay, key / mouse / consumer down-up,
  mouse move, 0xFF end, CRC-32 (docs/protocol.md). Left: where the macro id and CRC go in the tag. Wire format of those rows found too ([groups u8], per group 2 bytes, per row a
  byte + 4 big-endian u16; FUN_142b62090). Left: the row's first two fields, the MA bytes, the other tags, G HUB's
  v1 / v2 session paths, then a keyboard to test.
- **0x8030 MR key** (record a macro on the keyboard): needs the keystrokes, which Lghub can't
  read without input-device access.
- **Analog keyboards** (PRO X TKL RAPID, G515 RAPID TKL, G512 X, PRO X2 RAPID, ...): done:
  rapid trigger and key priority on / off (0x1B08 fn 1/2 and 4/5, G HUB's Feature1B08AnalogKeys;
  that a get answers in bit 0 is ours, check on a keyboard). Left: actuation point and
  rapid-trigger sensitivity per key and globally (G HUB's AnalogSettings, written into the
  onboard profile over 0x8101 / 0x8102), click haptics, 0x1B0C analog buttons, 0x80A4 curves.
  Found: all six tags and their bytes (docs/protocol.md, re/notes/keyboard_profiles.txt):
  0x120 global actuation u16, 0x121 / 0x122 global rapid trigger / key priority on, 0x123 / 0x124
  per-key [control index, u16] (value x 100), 0x130 key-priority pairs. 0x130's mode = G HUB's BindingFeatureFlavor (distance /
  last input / ordinal / reverse ordinal / neutral). The control-index table is 0x1B10 (G HUB's CidMap; features.control_list). Reading the analog
  tags is built (device_settings.analog_profile, G HUB's read path fn 4 / 6 / 7 with the profile
  byte). Left: which 0x8102 function reports the active profile, then a page; writes (fn 9-11)
  stay off until a keyboard can confirm them (a wrong write breaks the onboard profile).
- **0x1B05 full key customization** (G HUB's "FKC": remap any key, per layer, with presets):
  large; needs a keyboard that has it. Not started.
- 0x4521 game mode on older keyboards done (bits from G HUB, key names from Logitech's HID++
  spec). 0x4523 disable controls (newer keyboards' game mode): fn 0 sets a bitmap of control
  indexes, fn 1 / fn 3 read game-mode bits, fn 2 [0, on | lock << 1] sets game mode (G HUB's
  Feature4523DisableControls); left: which index is which key. G HUB's game-mode presets hold
  control ids (CIDs, from the key pictures' inputRegions). The newer keyboards' depots are
  readable now: their game-mode preset (DISABLE_CONTROLS_PRESET in defaults_override.json) is
  empty by default, so no mapping there. fn 0's bitmap is built from a list of on / off flags by
  index (Feature4523DisableControls); which control each index is gets decided above it (not
  found). Needs a keyboard to read its control table. 0x8088 multi-lightbar: not started (no device known). Left out: 0x8051 Logi
  modifiers (G HUB uses it inside its key remapping, no setting of its own).
- Left out on purpose: 0x4540 layout, 0x4530 / 0x4531 multi-platform, 0x4220 lock-key state;
  G HUB's app has no setting for them.

### Headsets
- **Newer headsets (A50 X, A50, G522, A20 X, G325, PRO X3)**: G HUB lists auto sleep, factory
  reset, battery eco mode, rename, spatial sound, LED brightness and cross-device support for
  them (capabilities in G HUB's device list); none done yet, features to find in the agent.
- **Centurion (G735, PRO X 2)**: features 0x06xx (mic mute 0x0601, sidetone 0x0604, ANC 0x0605,
  mic gain 0x0611, onboard EQ 0x0636, ...) over G HUB's own transport.
  - Done: G HUB's transport (centurion.py): its built-in table of 16 headsets (pid, HID usage page /
    usage, prefix, length byte, packet size; static init 0x1402111c0), the packet layer's fragments
    and reassembly, and the transport's wrap / unwrap, under the normal HID++ code. Sidetone 0x0604
    over it, as G HUB scales it (steps from fn 2). Ours: byte 0 on the wire = the collection's
    report id. Check on a G735 / PRO X 2 / G325.
  - Left: the other 0x06xx features (0601 mic mute, 0605 ANC, 0611 mic gain, 0636 onboard EQ, ...),
    read the same way from G HUB's decoders; Centurion0003SubdevicePlain (devices behind the 0x0003
    bridge). Notes: re/notes/centurion.txt.
- **Others**:
  - 0x8320 jack detection done (headphone bit ours); 0x8305 bass tone done
  - 0x0200 / 0x0201 / 0x020D volume and EQ sets, 0x020E mic test
  - 0x0800 / 0x0801 / 0x0809 mixer, 0x0900-0x0909 voice processing on the headset
  - 0x0920 Bluetooth EQ
- **Blue VO!CE 2 on the newer devices**: done for the PRO X 2, Yeti GX and Yeti Orb (their
  depots, encrypted, hold the same BLUE_VOICE_2_SETTINGS presets; the PRO X 2 under another file
  name). Check that the PRO X 2's PipeWire name contains "PRO X 2". The PRO X3, A50 X and
  Yeti 2 ship no Blue VO!CE 2 presets (their voice processing is somewhere else; not looked at).
- 0x8370 mic mute and gain done (G HUB: channel 0, gain x 100, mute flipped on 0AD1 / 0AD2).
- 0x8360 headphone level done (type 2, x 100, the only control G HUB writes).
- 0x8350 mic monitoring done (G HUB's sidetone code: read fn 1 (i, i), write fn 2 (0, 1, level)).
- 0x0B01 iMetering: not a setting; G HUB streams the mic's level readings into its meters with it
  (Lghub's meters come from PipeWire). Nothing to do unless a meter source turns out better.

### Wireless and power
- **G HUB's device list**: read in full (61 of 72 encrypted files; the other 11 have keys outside
  G HUB's public channel, probably unreleased products). All its mice, keyboards, headsets,
  webcams, mics and lights are in the catalog, with pictures and layouts from their (encrypted)
  depots; racing gear is left out.
- **Pairing a device to a receiver**: done for LS1 / LS2 LIGHTSPEED receivers ("Pair a device"
  on the receiver's page and in Settings; G HUB's HPP10Command lock on register 0xB2: open 1 on
  LS1, 7 on LS2, close 2; which receiver is which from G HUB's receivers list). Check on a
  receiver. Left: LSX (c54f): only one device pairs with it (PRO X3 SUPERSTRIKE); G HUB's
  0x1894 fn 2 openLock takes 3 bytes, but no code path to it was found in G HUB 2026.6 (only its
  vtable; the one 0x1894 user saves pairing info), so it may be unused; re/notes/pairing.txt. The
  POWERPLAY hybrid: closed, no device in G HUB's list pairs with it; unpairing: G HUB has none for LS1 / LS2 / LSX / hybrid receivers (its unpair code is for
  Windows Bluetooth and "BLE Pro" receivers, none of which are in its receiver list); not planned.
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
- **LIGHTSYNC screen sampler**: grim on wlroots compositors; elsewhere the screen-sharing portal
  (screencast.py: ScreenCast session, restore token so it asks once, pipewiresrc at 160x90).
  Tested on Hyprland's portal (2026-10-20): 160x90 frames, about 16 a second. Hyprland only
  gives a restore token when "Allow a restore token" is ticked in its picker (it uses grim
  anyway). Left: a check on GNOME / KDE.
  Keyboards now use G HUB's own regions and key map (screen_sampler-kb.json); its region editor
  is built too, as G HUB's sample editor: move / resize, add (G HUB's centred box), delete (keys go
  to the background, as G HUB), rename, give keys or zones to a region, screenshot or your own
  picture behind. Ours: background keys are turned off.
- Audio visualizer: G HUB's per-key layout and its options (colour mode fixed / reactive /
  gradient, background, boost, max amplitude, noise thresholds, smooth animation; how each shapes
  the level is ours) and the clip zone.
- **Software effects done**: G HUB's own animations (Verticool, Contrastic, Ocean Wave, Lightning,
  Red White and Blue: its keyframe files, downloaded at first use), Starlight, Colour cycle
  and Echo press (key presses read from the keyboard's own reports: ours) with G HUB's settings.
  **Firmware effects** (the device plays them): HID++ effect ids and parameter bytes now from
  G HUB's feature_8070 / 8071_lighting_effects (docs/protocol.md), which also corrected Lghub's
  old table (colour wave is 4, not 8). Signature (algorithmic, ids 24 / 25) with two colours
  and its six styles (IMMERSE, Pulsar Point, G3 Signature, Reminds Me Of, Neon, Outer Space),
  Pulsar Point, Neutron Null, colour wave with direction. Check on a G515 / newer keyboard;
  ours: the two-colour period fixed at G HUB's default 50 ms. Not yet: the same signature
  styles as *software* effects on per-key keyboards without them in firmware (G HUB's
  SignatureAlgorithmicEffect players, ~2000 lines of vector maths each), and Smooth Star /
  Wave: G HUB has both effect types SMOOTH_STAR / SMOOTH_WAVE (14 / 15, done below) and
  signature types 16 / 17 that its UI also labels Smooth Star / Smooth Wave (firmware ids 18 / 19 on
  keyboards that have them). Type 17's builder is identical to Smooth Wave's, and type 16's style 0 (its
  Smooth Star) builds the same tree as Smooth Star, so both are done; type 16's other per-key styles are done too (Pulsar Point, G 3 Series, Remind Me
  Of, Neon, Outer Space; signature.py). Left: their zonal versions (the builder's zone groups are
  read: G HUB picks them by the device's zone mask, SIX / LEFT_SIDE / BOTTOM / HALO; the trees aren't ported), Astro Point (headsets), and G Tide's
  key lists (type 18: G Tide itself is done, signature.g_tide, with G HUB's timing and gradients; the
  id space of its 12 hard-coded key lists isn't found, so the rings are ours: nearest keys to the middle).
  Started: G HUB's frame-handler engine is ported (signature.py: sequencer, parallel, pause,
  gradient, gradient sampler, gradient tween, colour blend, its gradient stops and colour blend;
  tests). Done: Smooth Wave (its whole tree from G HUB's builder 0x14121b700: 23 tween
  keyframes, the blends and pauses) on per-key keyboards. Ours: 30 fps, which LEDs make G HUB's
  two extra groups (taken as the logo / indicator keys), restarting at the end. Default colours are
  G HUB's (#FF00AB / #00B8FC, from its keyboards' signature presets).
  Smooth Star done the same way (builder 0x141218ff0: startup glow, the gradient sweep, G HUB's
  starlight twinkles; ported StartupFrameHandler and StarlightFrameHandler too). Its zonal roots
  (+0x190 / +0x1b0) not used yet.
  Factory found (0x1411e5db0: effect type -> builder; re/notes/lighting.txt). Left: the signature
  types 16-18 (builders 0x141204170 / 0x14120fe90 / 0x141214500; styles Pulsar Point, G 3 Series, Remind Me Of, Neon, Outer Space,
  Astro Point) from their builders (re/notes/lighting.txt), check on a real keyboard. The keyframe editor (Freestyle) is done: frames,
  length, curve, order, preview; saved in G HUB's keyframe format. Effects on zonal devices done
  (starlight, colour cycle, audio, echo press on clicks, screen sampler with G HUB's zone regions). Per-key frames use
  G HUB's single-value call for shared colours; its other calls are in docs/protocol.md (fn 2
  consecutive, fn 5 ranges; fn 3 / 4 delta-compressed, whose packing wasn't found). Not used: little
  gain over fn 1 / 6 and nothing to check it on; check animation smoothness on a real keyboard first.

### App
- **Update notice and "Update now"**: built (update.py, update_ui.py; GitHub releases with a
  SHA-256 and an SSH signature, daily anonymous check, banner, Settings card, tray item, backup and
  rollback). Releases: re/tools/release.py (local). Tested 0.9.0 -> 0.9.1 (2026-10-20).
- Low-battery notifications done (G HUB's LOW 30 % / CRITICAL 15 %; checking every 5 minutes is
  ours). Game-profile notifications and DPI / profile notices for onboard mice (G HUB's
  OSD_DPI_CHANGED / OSD_PROFILE_CHANGED from 0x8100 events) done. Report-rate notices (0x8061
  event) done.
- G HUB's audio button / macro actions done through PipeWire: cycle equalizer, toggle surround,
  cycle output / input, mic gain and volume up / down / mute, with its notices (OSD_EQUALIZER_CYCLE,
  OSD_SURROUND_SOUND_TOGGLE_*, OSD_AUDIO_OUTPUT / _INPUT), and sidetone / bass up / down (the
  first headset that has it; step 10 is ours), the advanced equalizer toggle and "switch to this
  audio device" (the first Logitech headset or mic: ours, the action names no device). Left out:
  treble up / down (no headset with a treble setting known).
- Game scan done (G HUB scans for installed games): Steam, Heroic (Epic, GOG), Legendary, Lutris.
- Tray icon done (G HUB's system tray: devices with battery, Blue VO!CE / equalizer / surround
  switches, Open Lghub, Quit Lghub (what Quit does is ours); StatusNotifierItem + dbusmenu, the
  installed Lghub / G HUB icon). config.json "tray": false turns it off.
- Settings page done (G HUB's general settings: notifications, tray, persistent profile). Not
  ours to copy: language (Lghub is English only), analytics, G HUB updates.
- **Firmware updates**: not planned (a mistake can brick a device).
- **Discord / OBS integrations**: not planned.
- **Racing wheels and pedals** (0x8123-0x8140): nobody here owns one.
- **Devices with screens** (0x0A00-0x0A02, 0x8103 Screen..., 0x8130 game data): not started.

## 3. Upkeep

- Keep `docs/protocol.md` current when a protocol detail is found or confirmed on a device.
- `fetch.py` (APO hashes), `depots.py` (depot paths, the icon's offset and hash) and the DLL
  modules (`micopt.c`, `hx2e.c`, `bv2.c`: RVAs and export names) are for G HUB 2026.6. A newer
  G HUB moves the depots; the code fails cleanly and keeps working without the new files.
- Re-check this list against a newer G HUB now and then: `Feature####` class names in the
  agent's strings.
- Native code (`bridge/*.c`) is at 0 under clang-tidy (LLVM 23: clang-analyzer, bugprone, cert,
  performance, portability), gcc -fanalyzer and SonarQube, checked 2026-10-25. One check is off:
  Annex K (`memcpy_s` / `snprintf_s`), which glibc doesn't have; the bridges check every copy's
  bounds themselves. Keep it at 0 when the bridges change.
