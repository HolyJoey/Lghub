# Blue VO!CE for Linux

Logitech's Blue VO!CE microphone effects for the G Pro X headset, on Linux. The official
G HUB software is Windows-only.

This is not a remake: it runs **Logitech's own Blue VO!CE DSP** — the audio effect G HUB
installs on Windows — natively, inside a small PipeWire filter (no Wine), and gives you its
output as a normal microphone that any app can use. The output is bit-for-bit identical to the
Windows effect for all 22 presets.

![Voice page with live levels and the G HUB presets](docs/screenshots/voice.png)

## What it does

- **Blue VO!CE on/off** — off is a clean pass-through, so apps keep their microphone
- **All 22 G HUB presets** for the G Pro X — Broadcaster, AM Radio, FM Station, the pro-player
  presets and more, with the exact values G HUB uses
- **Every effect, live** — high-pass filter, noise reduction, noise gate, 3-band voice EQ,
  de-esser, compressor and limiter, each with the same controls as G HUB's advanced mode;
  changes crossfade in without clicks
- **A virtual microphone** — “Blue VO!CE Microphone” shows up in Discord, OBS, your browser and
  everything else, or becomes your default input with one switch
- **Your own presets** — save, import and export
- **Live meters** for your microphone and the processed voice
- **Runs in the background** — closing the app keeps the virtual microphone working

## Screenshots

| Effects | Microphone |
| --- | --- |
| ![Every Blue VO!CE stage with its controls](docs/screenshots/effects.png) | ![Input device, default microphone, latency and service](docs/screenshots/microphone.png) |

## Install

```bash
git clone https://github.com/HolyJoey/Lghub.git
cd Lghub
./install.sh
```

The installer builds one small native helper, downloads Logitech's Blue VO!CE files straight
from G HUB's own update server (they are not in this repository) and checks their SHA-256, adds
a menu entry, and starts a user service. Nothing needs root, and Wine is not used.
`./uninstall.sh` reverses all of it.

**Requirements:** an x86-64 PC, Python 3 with GTK 4 and libadwaita, PipeWire with WirePlumber,
and gcc with the PipeWire headers to build the helper.

| Distro | Packages |
| --- | --- |
| Debian / Ubuntu | `python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gcc libpipewire-0.3-dev` |
| Fedora | `python3-gobject gtk4 libadwaita gcc pipewire-devel` |
| Arch | `python-gobject gtk4 libadwaita gcc libpipewire` |

## Using it

Open **Blue VO!CE** from your menu, pick a preset, and choose **Blue VO!CE Microphone** as the
input in your apps (or turn on *Use as default microphone*). The *Microphone* page picks your
G Pro X automatically when it is plugged in; you can choose any other microphone there too.

## How it works

```
G Pro X mic ──► bluevoice-bridge (PipeWire filter, runs Logitech's DSP in-process) ──► “Blue VO!CE Microphone”
```

- **`logi_audio_dts_studio_capture_apo.dll`** is the Windows audio effect G HUB installs for
  Blue VO!CE, built on DTS MicOpt. `fetch.py` takes it from G HUB's `driver_audio_apo` package
  and the presets from the `pro_headset` package.
- The DLL exports the DSP itself (`dts_micopt_init`, `dts_micopt_set`, `dts_micopt_process`, …).
  **`bridge/peloader.c`** loads the DLL into the Linux process — sections, relocations, and
  stand-ins for the handful of Windows calls the DSP path makes — and **`bridge/micopt.c`** drives
  it exactly as the Windows effect does (same block size, defaults and parameter encoding).
- **`bridge/bluevoice-bridge`** is the PipeWire filter: microphone in, MicOpt in 256-frame blocks,
  virtual microphone out, 8 ms of added delay. Settings changes build a new DSP instance, warm it
  up and crossfade, so switching presets doesn't click.
- **`engine.py`** (the `lghub-bluevoice` user service) runs the bridge, opens your microphone only
  while some app uses Blue VO!CE, follows replugs, and applies your settings; **`app.py`** is the
  GTK interface.

[docs/apo-parameters.md](docs/apo-parameters.md) lists every Blue VO!CE parameter with its units
and defaults, as recovered from the DLL.

### Verified against Windows

`host/bluevoice_host.c` hosts the same DLL the way the Windows audio engine does (as a COM audio
effect, under Wine), and `host/compare_native.py` runs both on the same recording. For every
stage and all 22 G HUB presets the native output is identical, sample for sample.

## Troubleshooting

- **No “Blue VO!CE Microphone”** — `systemctl --user status lghub-bluevoice` and
  `journalctl --user -u lghub-bluevoice` show what the service is doing.
- **Install says a depot doesn't match** — Logitech published a new version. Install G HUB's
  files from another source with `./install.sh --depot-dir DIR` (a folder holding
  `driver_audio_apo.depot` and `pro_headset.depot`), or open an issue.

## Disclaimer

Not affiliated with Logitech. Blue VO!CE, G HUB and G Pro X are Logitech trademarks; DTS is a
trademark of DTS, Inc. This project only contains its own code; Logitech's files are downloaded
from Logitech at install time and used on your own machine.
