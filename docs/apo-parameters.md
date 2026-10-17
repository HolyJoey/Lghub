# Blue VO!CE 1 APO parameters

Source: `logi_audio_dts_studio_capture_apo.dll` (DTS MicOpt), CLSID
`{4BD94DA9-BE3B-4523-9072-6EAD0AF5505E}`. The APO reads every parameter from the endpoint
property store under fmtid `{BA8CAF9F-6B5A-4DDE-830B-29E9EAF6E293}`. Enables are `VT_I4`,
everything else `VT_R4`. A missing value leaves the APO default in place.

Processing order: dpop → nr → exp → veq → des → comp → lim.

| pid | name | default | notes (from `dts_micopt_set`) |
|---|---|---|---|
| 2 | micopt.meter_enable | | |
| 100 | micopt.enable | 1 | |
| 101 | micopt.balance | 0 | |
| 102 | micopt.volume | 1.0 | linear |
| 200 | dpop.enable | | high-pass ("de-popper") |
| 201 | dpop.freq | 80 Hz | |
| 300 | nr.enable | | noise reduction |
| 301 | nr.release | 75 ms | |
| 302 | nr.sensitivity | 25 | |
| 303 | nr.bias | 2.5 | |
| 304 | nr.attenuation_max | -20 dB | converted to a linear floor (1 − gain) |
| 400 | exp.enable | | expander / noise gate |
| 401 | exp.attack | 5 ms | two time constants: t and 20·t (min 5 ms) |
| 402 | exp.release | 250 ms | two time constants: t and 0.05·t (min 5 ms) |
| 403 | exp.hysteresis | 5 ms | converted to samples |
| 404 | exp.ratio | 2 | used only if > 1 |
| 405 | exp.thresh | -48 dBFS | |
| 406 | exp.thresh_auto_enable | 0 | |
| 407 | exp.thresh_auto_sense | 20 | |
| 408 | exp.attenuation_max | -20 dB | forced negative |
| 500 | veq.enable | | 3-band voice EQ |
| 501/504/507 | veq.{low,mid,high}_gain | 1.0 | **linear** gain (1.0 = 0 dB) |
| 502/505/508 | veq.{low,mid,high}_freq | 250 / 3000 / 8000 Hz | |
| 503/506/509 | veq.{low,mid,high}_width | 1 / 4 / 1 | |
| 600 | des.enable | | de-esser |
| 601 | des.attack | 5 ms | t and 5·t |
| 602 | des.release | 250 ms | t and 0.2·t |
| 603 | des.ratio | 4 | stored as slope 1 − 1/ratio |
| 604 | des.thresh | | dBFS |
| 605 | des.freq | 8000 Hz | |
| 700 | comp.enable | | compressor |
| 701 | comp.attack | 5 ms | t and 5·t |
| 702 | comp.release | 250 ms | t and 0.2·t |
| 703 | comp.ratio | 4 | stored as slope 1 − 1/ratio |
| 704 | comp.thresh | -20 dBFS | |
| 705 | comp.makeup | 1.0 | linear |
| 800 | lim.boost | 1.0 | linear (presets use 2–10, i.e. +6 to +20 dB) |
| 801 | lim.attack | 5 ms | t and 5·t |
| 802 | lim.release | 250 ms | t and 0.2·t |

The APO also asks for pids 1, 150, 152, 350, 450, 452, 454, 650, 750, 752, 850, 852, 854
(probably meter read-backs); returning empty values is fine.

G HUB preset JSON → these names: see `host/preset_to_params.py`.
