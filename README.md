# Lghub

Lghub is Logitech G HUB, reverse-engineered for Linux: the settings G HUB gives you for
Logitech G headsets, mice, keyboards and webcams, running natively (no Wine). Where G HUB's
features are Logitech's own code, like Blue VO!CE and DTS surround, Lghub runs that same code
from G HUB's packages; everything else talks to the devices directly, the way G HUB does.
Devices show up as you plug them in, including wireless ones behind a LIGHTSPEED, Unifying or
Bolt receiver; pick one to change its settings.

![Devices](docs/screenshots/home.png)

## Headsets

The G Pro X, G Pro X Wireless and G733 open on Blue VO!CE; other headsets get the page
described under *Keyboards and the rest*.

**Blue VO!CE.** Logitech's own voice processing (it runs the DTS code G HUB ships, so all
presets sound exactly as on Windows), on a new input device called *Blue VO!CE Microphone*
that Discord, OBS, your browser or anything else can use:

- every Blue VO!CE preset G HUB has for the headset
- all the advanced controls: high-pass, noise reduction, noise gate, voice EQ, de-esser,
  compressor and limiter. Changes apply while you talk, without clicks
- your own presets, with import and export
- an on/off switch that keeps the device around, so your apps don't lose their mic

It keeps running in the background, and your real mic is only opened while some app is
recording from Blue VO!CE.

**Equalizer.** G HUB's 10-band headset equalizer presets (Flat, FPS, MOBA, Bass Boost,
Cinematic, Communications) and bands, 32 Hz to 16 kHz, on a new output *… (Equalizer)* in front of the
headset. The presets come from Logitech's own files; the filters doing the work are PipeWire's,
not Logitech's DSP.

**Blue VO!CE 2.** On Yeti mics and the G735, the newer voice chain G HUB runs there
(Logitech's own DTS ClearVoice 2 processing), with G HUB's presets for the mic (Broadcaster,
High Voice, Warm and Vintage, ...) and a switch for each stage: high-pass, noise reduction,
noise gate, compressor, equalizer, de-popper, de-esser, limiter, each with G HUB's own controls.
Plus G HUB's voice effects (Robot, Helium Chipmunk, Demon, ...: voice changer, chorus, flanger,
reverb, delay, ring modulator). Untested on a real Yeti.

**Games.** Settings that switch on while a game runs, like G HUB's game profiles: add a game by
its executable (Proton games too) or Steam App ID, and its Blue VO!CE, equalizer and surround
settings come on when it starts and go back when it closes.

**Surround.** G HUB's DTS Headphone:X 2.0 virtual 7.1, running Logitech's own DTS processing
with your headset's tuning (G Pro X, G Pro X Wireless, G733 and more), on a new output
*… (Surround 7.1)*. Games set to 7.1 get every speaker placed around you. G HUB's rooms
(Gaming, Entertainment, Sports) and per-channel volumes. It only runs while something plays, and it works together with the equalizer.

**Headset.** Sidetone, volume and mic level from the headset's sound card, plus lighting,
battery and the equalizer built into the headset (works on any computer or console) on headsets
that have them.

| Voice | Effects |
| --- | --- |
| ![Voice](docs/screenshots/voice.png) | ![Effects](docs/screenshots/effects.png) |
| **Equalizer** | **Surround** |
| ![Equalizer](docs/screenshots/equalizer.png) | ![Surround](docs/screenshots/surround.png) |

## Mice

DPI levels (and the default and DPI-shift level), report rate, what every button does
(including keystrokes and a G-Shift layer), lighting, and the profiles stored in the mouse.
Mice that have them also get the scroll wheel (ratchet or free spin, SmartShift, ratchet
force) and angle snapping.
**Macros** like G HUB's: keystrokes, text, media and system actions, apps, web pages and
recorded sequences (once, while held, or on/off), put on any button but the left one. They
run in the background service, the same way G HUB does it (HID++ 0x8110: only buttons with a
macro stop clicking by themselves). DPI and profile macros switch the mouse's own DPI and
profiles.
Like G HUB's on-board memory mode, everything is saved *in the mouse*, so it keeps working on
any computer and nothing has to run in the background. Before the first change, the mouse's
memory is backed up to `~/.local/share/lghub-bluevoice/backups/`.

| Sensitivity | Buttons | Lighting |
| --- | --- | --- |
| ![Mouse](docs/screenshots/mouse.png) | ![Buttons](docs/screenshots/mouse-buttons.png) | ![Lighting](docs/screenshots/mouse-lighting.png) |

Wireless mice also show their battery.

## Keyboards and the rest

Keyboards, other headsets, the G560 speakers, POWERPLAY and anything else Logitech: Lghub
asks the device what it can do and shows that. Keyboards also get macros on their G-keys (three sets, switched with M1-M3) and a
per-key lighting page drawn from G HUB's own key layout, sent over HID++ 0x8081 with G HUB's
key-to-LED table (0x8080 on older keyboards). Lighting zones and effects, brightness, report
rate, Fn keys, game mode, Easy-Switch, angle snapping, sidetone, on-board memory and battery. Devices with a USB sound card (headsets,
speakers, Yeti mics) also get its controls.

![Keyboard](docs/screenshots/keyboard.png)

## Webcams

A live preview, and every setting the camera has: brightness, contrast, saturation,
sharpness, white balance, exposure, focus, zoom, pan and tilt. Webcams forget their settings
when unplugged, so Lghub saves them and puts them back whenever the camera shows up again.

![Webcam](docs/screenshots/webcam.png)

## Install

```bash
git clone https://github.com/HolyJoey/Lghub.git
cd Lghub
./install.sh
```

You need an x86-64 PC with PipeWire, Python with GTK 4 and libadwaita, and gcc to build the
Blue VO!CE helper:

| Distro | Packages |
| --- | --- |
| Debian / Ubuntu | `python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gcc libpipewire-0.3-dev alsa-utils` |
| Fedora | `python3-gobject gtk4 libadwaita gcc pipewire-devel alsa-utils` |
| Arch | `python-gobject gtk4 libadwaita gcc libpipewire alsa-utils` |

The installer downloads Logitech's audio effects (Blue VO!CE and DTS Headphone:X), G HUB's
equalizer presets and G HUB's app icon from G HUB's own update server (none of it is in this
repo), checks the hashes, builds the helpers, adds a menu entry and starts a user service. `./uninstall.sh` undoes all of it. Later, the first time a device shows up, the
app fetches its product picture from the same server (and, for the G733, its Blue VO!CE
presets): just those files, a few hundred KB.

Mice and keyboards need permission to talk to the device, and macros to type. One udev rule
file does both; this is the only step that needs root:

```bash
printf '%s\n' 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", TAG+="uaccess"' \
  'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' \
  | sudo tee /etc/udev/rules.d/70-lghub.rules
sudo udevadm control --reload && sudo udevadm trigger
```

Then open **Lghub** from your menu (or run `lghub`).

## Is it heavy?

No. Measured on a laptop (Intel Alder Lake), as a share of one CPU core:

| Part | While in use | Otherwise |
| --- | --- | --- |
| Background service (keeps everything below running) | | 0.2%, 30 MB |
| Blue VO!CE | about 4% while you talk, 8 ms delay | nothing: your mic is only opened while an app records |
| Surround | about 1.5% while something plays | nothing: the headset can go idle |
| Equalizer | about 0.5% while something plays | nothing (and not running when switched off) |
| Webcam preview | about 5% in the app while it shows | nothing (off, or app closed) |
| Mice, keyboards | | nothing: their settings are stored in the device |

The app itself does nothing once closed.

## How it works

- **Surround.** The DTS Headphone:X effect (`logi_audio_hx2e_render_apo.dll`) doesn't export
  its DSP, but the C++ object that holds it has a plain vtable: `bridge/hx2e.c` creates it with
  the DLL's own factory and calls Init (the headset's tuning), SetStreamsParams and Process
  the way G HUB's effect does. `surround-bridge` puts that behind a 7.1 PipeWire output.
- **Blue VO!CE.** The Windows effect (`logi_audio_dts_studio_capture_apo.dll`) exports its DSP
  directly. `bridge/peloader.c` maps the DLL into a normal Linux process and gives it the few
  Windows functions it needs; `bridge/micopt.c` calls it the way the Windows effect does, and
  `bluevoice-bridge` wraps that in a PipeWire filter. Every parameter is written down in
  [docs/apo-parameters.md](docs/apo-parameters.md). The output was checked sample by
  sample against the real effect running under Wine.
- **Mice, keyboards, receivers.** Logitech's HID++ 2.0 protocol over `/dev/hidraw`
  (`hidpp.py`): ask the device which features it has, then use them. Onboard profiles
  (`mouse.py`) are read, changed and written back with their checksum, then read again to
  make sure.
- **Webcams.** The standard Linux video interface, V4L2 (`v4l2.py`), for the settings and
  the preview (MJPEG frames, decoded by GTK).
- **Headset sound card.** ALSA's mixer (`headset.py`).
- **Background service.** `engine.py` keeps Blue VO!CE, the equalizer and surround running and
  puts webcam settings back. `systemctl --user status lghub-bluevoice` shows it.

Which device is which comes from a small table of model facts (`devices.py`): USB ids,
lighting zones, and so on. `depots.py` knows where each model's G HUB package lives and reads
just the files it needs out of it with HTTP range requests.

## Trying it without the hardware

```bash
LGHUB_FAKE_DEVICES=0aaa,c08b,c539,c33f,082d lghub
```

pretends a G Pro X, a G502 HERO, a receiver with a G502 LIGHTSPEED, a G815 and a C920 are
plugged in. Mice and keyboards are simulated (`simulate.py`), and the tests run against the
same simulator: `python3 -m unittest discover tests`. `082d@3-4` makes the camera on USB port
3-4 pose as a C920. The mouse, keyboard and wireless screenshots above are from the
simulator. The webcam screenshot is a real camera.

## Not there yet

- Keyboard onboard profiles; Blue VO!CE 2 on the PRO X 2;
  the Yeti's mic monitoring and gain over HID++; the 5-band PRO equalizer.
- Most devices here have only met the simulator. If something doesn't work on yours, open an
  issue with `journalctl --user -u lghub-bluevoice` and what the device's page says.

## If something's off

`systemctl --user status lghub-bluevoice` and `journalctl --user -u lghub-bluevoice` show what
the service is doing. If a mouse or keyboard page says it can't talk to the device, check the
udev rule above and replug it. If the installer says a download doesn't match, Logitech has
released new files; open an issue. If you have the files from somewhere else, point the
installer at them with `./install.sh --depot-dir DIR`.

## License

MIT, see [LICENSE](LICENSE). That covers the code in this repo. Logitech's files that Lghub
downloads (the Blue VO!CE and DTS Headphone:X effects, Blue VO!CE and equalizer presets,
product pictures and the G HUB icon) are not part of it and stay under Logitech's own terms.

Not affiliated with Logitech. Logitech, G HUB, Blue VO!CE, LIGHTSPEED, the G HUB icon and the
product names are Logitech's trademarks; DTS and DTS Headphone:X are DTS, Inc.'s.
