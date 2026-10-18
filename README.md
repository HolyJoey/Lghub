# Lghub

Logitech G HUB for Linux, more or less. I use a G Pro X, a G502 and a C920, and G HUB only
runs on Windows, so this does the same jobs natively: no Wine, no Windows, nothing running
that you don't need.

It started as Blue VO!CE for the G Pro X. That one turned out to be a Windows audio effect,
not something in the headset, so this project loads Logitech's own DSP on Linux and puts the
result on a virtual microphone. Same code Logitech ships, so it sounds the same: all 22
presets come out identical to the Windows effect, sample for sample. The rest of the devices
are talked to directly, the way G HUB does.

![Devices](docs/screenshots/home.png)

Open the app, pick a device, change what you want. Devices show up and disappear as you plug
them in, including wireless ones behind a LIGHTSPEED, Unifying or Bolt receiver. The first
time a device shows up, Lghub fetches its product picture from G HUB's update server: only
that picture, a few hundred KB, not the whole package.

## Headsets

**Blue VO!CE.** A new input device called *Blue VO!CE Microphone* that Discord, OBS, your
browser or anything else can use:

- every Blue VO!CE preset G HUB has for the G Pro X (and the Pro X Wireless set)
- all the advanced controls: high-pass, noise reduction, noise gate, voice EQ, de-esser,
  compressor and limiter. Changes apply while you talk, without clicks
- your own presets, with import and export
- an on/off switch that keeps the device around, so your apps don't lose their mic

It works with any microphone, not only the headset's. Your real mic is only opened while some
app is recording from Blue VO!CE.

**Equalizer.** 10 bands from 32 Hz to 16 kHz with a handful of presets, on a new output
*… (Equalizer)* in front of the headset. This one is ours (PipeWire's filters), not
Logitech's.

**Headset.** Sidetone, volume and mic level, set in the headset's own sound card.

| Voice | Effects |
| --- | --- |
| ![Voice](docs/screenshots/voice.png) | ![Effects](docs/screenshots/effects.png) |
| **Equalizer** | **Microphone** |
| ![Equalizer](docs/screenshots/equalizer.png) | ![Microphone](docs/screenshots/microphone.png) |

Other headsets (G733, G935, …) get the page described under *Keyboards and the rest*.

## Mice

DPI levels (and the default and DPI-shift level), report rate, what every button does
(including keystrokes and a G-Shift layer), lighting, and the profiles stored in the mouse.
Like G HUB's on-board memory mode, everything is saved *in the mouse*, so it keeps working on
any computer and nothing has to run in the background. Before the first change, the mouse's
memory is backed up to `~/.local/share/lghub-bluevoice/backups/`.

| Sensitivity | Buttons | Lighting |
| --- | --- | --- |
| ![Mouse](docs/screenshots/mouse.png) | ![Buttons](docs/screenshots/mouse-buttons.png) | ![Lighting](docs/screenshots/mouse-lighting.png) |

Wireless mice also show their battery.

## Keyboards and the rest

Keyboards, other headsets, the G560 speakers, POWERPLAY and anything else Logitech: Lghub
asks the device what it can do and shows that. Lighting zones and effects, brightness, report
rate, sidetone, on-board memory and battery. Devices with a USB sound card (headsets,
speakers, Yeti mics) also get its controls.

![Keyboard](docs/screenshots/keyboard.png)

## Webcams

Brightness, contrast, saturation, sharpness, white balance, exposure, focus, zoom, pan and
tilt: every setting the camera has. Webcams forget their settings when unplugged, so Lghub
saves them and puts them back whenever the camera shows up again.

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

The installer downloads Logitech's Blue VO!CE files from G HUB's own update server (they aren't in this repo), checks their hashes, builds the helper, adds a menu
entry and starts a user service. `./uninstall.sh` undoes all of it.

Mice and keyboards need permission to talk to the device. One udev rule does it; this is the
only step that needs root:

```bash
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="046d", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/70-lghub.rules
sudo udevadm control --reload && sudo udevadm trigger
```

Then open **Lghub** from your menu (or run `lghub`).

## Is it heavy?

No. Blue VO!CE uses about 4% of one CPU core while you talk and close to nothing otherwise,
and adds 8 ms of delay. The equalizer only runs while it's switched on. The app itself does
nothing once closed; mouse and keyboard settings live in the devices.

## How it works

- **Blue VO!CE.** The Windows effect (`logi_audio_dts_studio_capture_apo.dll`) exports its DSP
  directly. `bridge/peloader.c` maps the DLL into a normal Linux process and gives it the few
  Windows functions it needs; `bridge/micopt.c` calls it the way the Windows effect does, and
  `bluevoice-bridge` wraps that in a PipeWire filter. Every parameter is written down in
  [docs/apo-parameters.md](docs/apo-parameters.md). `host/` checks the result against the
  real effect under Wine.
- **Mice, keyboards, receivers.** Logitech's HID++ 2.0 protocol over `/dev/hidraw`
  (`hidpp.py`): ask the device which features it has, then use them. Onboard profiles
  (`mouse.py`) are read, changed and written back with their checksum, then read again to
  make sure.
- **Webcams.** The standard Linux video interface, V4L2 (`v4l2.py`).
- **Headset sound card.** ALSA's mixer (`headset.py`).
- **Background service.** `engine.py` keeps Blue VO!CE and the equalizer running and puts
  webcam settings back. `systemctl --user status lghub-bluevoice` shows it.

Which device is which comes from a small table of model facts (`devices.py`): USB ids,
lighting zones, and so on. `images.py` knows where each model's G HUB package lives and reads
just the picture out of it with HTTP range requests.

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

- DTS Headphone:X surround: Logitech's playback effects need a different way of loading.
- Per-key lighting, G-key macros, and keyboard onboard profiles.
- A live webcam preview.
- Most devices here have only met the simulator. If something doesn't work on yours, open an
  issue with `journalctl --user -u lghub-bluevoice` and what the device's page says.

## If something's off

`systemctl --user status lghub-bluevoice` and `journalctl --user -u lghub-bluevoice` show what
the service is doing. If a mouse or keyboard page says it can't talk to the device, check the
udev rule above and replug it. If the installer says a download doesn't match, Logitech has
released new files; open an issue. If you have the files from somewhere else, point the
installer at them with `./install.sh --depot-dir DIR`.

## License

MIT, see [LICENSE](LICENSE). That covers the code in this repo. Logitech's files that the
app downloads (the Blue VO!CE DLL, its presets and the product pictures) are not part of
it and stay under Logitech's own terms.

Not affiliated with Logitech. Logitech, G HUB, Blue VO!CE, LIGHTSPEED and the product names
are Logitech's trademarks; DTS is DTS, Inc.'s.
