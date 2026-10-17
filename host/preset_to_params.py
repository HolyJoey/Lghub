#!/usr/bin/env python3
"""Convert one Blue VO!CE preset from G HUB's *_device_presets.json into the
"name value" lines bluevoice_host.exe reads (APO parameter names)."""
import json
import sys


# APO parameter name -> (section, key) in G HUB's blueVoiceSettings.settings
FIELDS = {
    "micopt.balance": (None, "balance"), "micopt.volume": (None, "volume"),
    "dpop.enable": ("dePopper", "enabled"), "dpop.freq": ("dePopper", "frequency"),
    "nr.enable": ("noiseReduction", "enabled"), "nr.release": ("noiseReduction", "release"),
    "nr.sensitivity": ("noiseReduction", "sensitivity"), "nr.bias": ("noiseReduction", "bias"),
    "nr.attenuation_max": ("noiseReduction", "attenuationMax"),
    "exp.enable": ("expander", "enabled"), "exp.attack": ("expander", "attack"),
    "exp.release": ("expander", "release"), "exp.hysteresis": ("expander", "hysteresis"),
    "exp.ratio": ("expander", "ratio"), "exp.thresh": ("expander", "threshold"),
    "exp.thresh_auto_enable": ("expander", "thresholdAutoEnabled"),
    "exp.thresh_auto_sense": ("expander", "thresholdAutoSensibility"),
    "exp.attenuation_max": ("expander", "attenuationMax"),
    "veq.enable": ("voiceEq", "enabled"),
    "des.enable": ("deEsser", "enabled"), "des.attack": ("deEsser", "attack"),
    "des.release": ("deEsser", "release"), "des.ratio": ("deEsser", "ratio"),
    "des.thresh": ("deEsser", "threshold"), "des.freq": ("deEsser", "frequency"),
    "comp.enable": ("compressor", "enabled"), "comp.attack": ("compressor", "attack"),
    "comp.release": ("compressor", "release"), "comp.ratio": ("compressor", "ratio"),
    "comp.thresh": ("compressor", "threshold"), "comp.makeup": ("compressor", "makeup"),
    "lim.boost": ("limiter", "boost"), "lim.attack": ("limiter", "attack"),
    "lim.release": ("limiter", "release"),
}
for _band in ("low", "mid", "high"):
    for _apo, _key in (("gain", "gain"), ("freq", "frequency"), ("width", "width")):
        FIELDS[f"veq.{_band}_{_apo}"] = ("voiceEq", (_band, _key))


def preset_params(s):
    """APO parameters for one preset. Fields a preset leaves out are omitted, so the APO
    falls back to its own defaults (as it does under G HUB)."""
    p = {"micopt.enable": 1, "micopt.meter_enable": 0}
    for name, (section, key) in FIELDS.items():
        node = s if section is None else s.get(section, {})
        if isinstance(key, tuple):
            node, key = node.get(key[0], {}), key[1]
        value = node.get(key)
        if value is None:
            continue
        p[name] = int(value) if isinstance(value, bool) else value
    return p


def load_presets(path):
    out = {}
    for entry in json.load(open(path))["presets"]:
        bv = entry.get("blueVoiceSettings")
        if bv:
            out[bv["description"]["name"].removeprefix("BLUE_VOICE_PRESET_")] = bv["settings"]
    return out


if __name__ == "__main__":
    presets = load_presets(sys.argv[1])
    if len(sys.argv) < 3:
        print("\n".join(presets))
        sys.exit(0)
    for k, v in preset_params(presets[sys.argv[2]]).items():
        print(k, v)
