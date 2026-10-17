# Lghub — Blue VO!CE on Linux (work in progress)

Logitech's Blue VO!CE microphone processing for the G Pro X headset, on Linux, using
Logitech's own DSP: the Windows audio effect from G HUB runs under Wine and its output is
published as a virtual PipeWire microphone.

**Status:** the real Blue VO!CE DSP runs and processes audio offline with all 22 G Pro X
presets. The live PipeWire microphone and the desktop app are not finished — see
[TODO.md](TODO.md).

This repository contains no Logitech or DTS files. They are downloaded from Logitech's own
update server at install time.

## Layout

- `host/` — `bluevoice_host.exe` (Windows, built with MinGW, runs under Wine): loads the APO,
  feeds it parameters, processes float32 mono on stdin → stdout; `preset_to_params.py`
- `bridge/` — `bluevoice-bridge` (native, libpipewire): mic → host → virtual microphone
- `tools/` — extractors for G HUB's installer, depot files and embedded DLLs
- `docs/apo-parameters.md` — every Blue VO!CE parameter, units and defaults

## Building

```bash
x86_64-w64-mingw32-gcc -O2 -o host/bluevoice_host.exe host/bluevoice_host.c -lole32 -loleaut32 -luuid -lpropsys
gcc -O2 -o bridge/bluevoice-bridge bridge/bluevoice_bridge.c $(pkg-config --cflags --libs libpipewire-0.3) -lpthread
```
