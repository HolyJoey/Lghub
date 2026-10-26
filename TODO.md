# Roadmap

What's still open in Lghub. What works is in the [README](README.md); the protocols are in
[docs/protocol.md](docs/protocol.md).

## Towards 1.0

0.9.9 has everything that can be built without the devices. 1.0 comes after checks on real hardware:

- **A mouse**: DPI, report rate, buttons, the lighting stored in its profiles, switching profiles.
- **The G Pro X headset**: the sidetone slider (or the page's reason why there isn't one), surround by ear,
  the PRO equalizer, Blue VO!CE, the equalizer together with surround.
- **The C920 webcam**: the preview and its picture controls.

Most devices have only met Lghub's simulator so far. If you have one, a report helps a lot: open an issue
with the "Device report" form.

## Known blind spot: keyboards

Nobody testing Lghub has a Logitech keyboard yet. Keyboards get their live settings (lighting, per-key
lighting and effects, game mode, Fn keys, G-key macros, report rate, Easy-Switch, the analog keys'
switches), but none of it has been checked on a real keyboard.

What's stored in a keyboard's onboard profile (key assignments, macros, per-key actuation, its lighting)
is shown but can't be changed yet: a wrong write would overwrite a profile, so writing stays off until
someone checks it on a keyboard. 1.0 ships with it off unless a keyboard owner's report comes in first.

## Needs a device to finish

- Light-strip signature effects on the G735, G512 X, G713 and G715: the order of the strip's LEDs comes
  from the device itself.
- A few newer-headset settings whose values G HUB's own code doesn't name: host switching, the mix's input
  choice, noise exposure levels, usage time.
- The Yeti 2's screen pictures and mascot (its brightness and orientation work).

## Still open compared with G HUB

- Pairing on LSX and POWERPLAY receivers.
- Recording a macro with a keyboard's MR key (needs raw keyboard input).
- Not planned: firmware updates (a mistake can brick a device), racing wheels and pedals, Discord / OBS
  integrations, languages other than English.

## Progress

Rough estimates of how much of each area's G HUB features Lghub has (overall about 88%), not measurements.

| Area | Done | What's left |
| --- | --- | --- |
| Blue VO!CE (G Pro X, G733) | 100% | a check on the G Pro X |
| Blue VO!CE 2 (Yetis, G735, PRO X 2) | 95% | a check on a mic |
| Surround, equalizer | 100% | a check on the G Pro X |
| PRO 5-band equalizer | 95% | a check on the G Pro X |
| Mice | 94% | a check on a mouse |
| Keyboards | 88% | changing the onboard profile; a check on a keyboard |
| Headsets (other than the voice chain) | 85% | the settings above; a check on a newer headset |
| Yeti controls | 100% | a check on a Yeti |
| Litra lights | 90% | a check on a Litra Glow / Beam |
| Webcams | 90% | a check on the C920 |
| Wireless (receivers, Bluetooth, power) | 80% | pairing on LSX / POWERPLAY |
| Lighting | 97% | the light strips' signature effects |
| App features | 85% | checks on GNOME / KDE (tray, screen sampler) |
| Background service | 95% | measured: 0.2% CPU, 28 MB idle |
