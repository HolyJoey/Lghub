"""Blue VO!CE presets and parameters.

Parameter names are the APO's own (see docs/apo-parameters.md). PARAMS lists each one once:
its default, where G HUB keeps it in *_device_presets.json, and how the app shows it.
DEFAULTS, FIELDS, LINEAR, STAGES and OUTPUT_PARAM are derived from it.
"""
import json
import math

VOLUME = 'micopt.volume'  # the output level, shown above the stages

# (APO name, APO default, G HUB location, UI slider)
#   G HUB location: (section, key) in blueVoiceSettings.settings; section None = top level,
#                   key may be (band, key) for the voice EQ. None = G HUB doesn't store it.
#   UI slider: (label, min, max, step, unit), or None. Ranges cover all G HUB presets.
#              'dB' on a linear-gain parameter (see LINEAR) is converted for display.
# Defaults come from the DLL's own initialisation (FUN_18000e080); a parameter left out of the
# params file keeps its default, exactly as under G HUB.
PARAMS = [
	('micopt.enable', 1, None, None),
	('micopt.meter_enable', 0, None, None),
	('micopt.balance', 0.0, (None, 'balance'), None),
	(VOLUME, 1.0, (None, 'volume'), ('Output level', -30, 0, 0.5, 'dB')),

	('dpop.enable', 0, ('dePopper', 'enabled'), None),
	('dpop.freq', 80.0, ('dePopper', 'frequency'), ('Cutoff', 20, 300, 1, 'Hz')),

	('nr.enable', 0, ('noiseReduction', 'enabled'), None),
	('nr.attenuation_max', -20.0, ('noiseReduction', 'attenuationMax'), ('Maximum reduction', -30, 0, 1, 'dB')),
	('nr.sensitivity', 25.0, ('noiseReduction', 'sensitivity'), ('Sensitivity', 0, 30, 1, '')),
	('nr.bias', 2.5, ('noiseReduction', 'bias'), ('Bias', 0, 10, 0.1, '')),
	('nr.release', 75.0, ('noiseReduction', 'release'), ('Release', 10, 1000, 5, 'ms')),

	('exp.enable', 0, ('expander', 'enabled'), None),
	('exp.thresh', -48.0, ('expander', 'threshold'), ('Threshold', -80, 0, 1, 'dB')),
	('exp.ratio', 2.0, ('expander', 'ratio'), ('Ratio', 1, 20, 0.5, ':1')),
	('exp.attenuation_max', -20.0, ('expander', 'attenuationMax'), ('Maximum reduction', -60, 0, 1, 'dB')),
	('exp.attack', 5.0, ('expander', 'attack'), ('Attack', 0.1, 100, 0.1, 'ms')),
	('exp.release', 250.0, ('expander', 'release'), ('Release', 10, 2000, 10, 'ms')),
	('exp.hysteresis', 5.0, ('expander', 'hysteresis'), ('Hysteresis', 0, 200, 1, 'ms')),
	('exp.thresh_auto_enable', 0, ('expander', 'thresholdAutoEnabled'), None),
	('exp.thresh_auto_sense', 20.0, ('expander', 'thresholdAutoSensibility'), None),

	('veq.enable', 0, ('voiceEq', 'enabled'), None),
	('veq.low_gain', 1.0, ('voiceEq', ('low', 'gain')), ('Low gain', -15, 15, 0.5, 'dB')),
	('veq.low_freq', 250.0, ('voiceEq', ('low', 'frequency')), ('Low frequency', 40, 600, 5, 'Hz')),
	('veq.low_width', 1.0, ('voiceEq', ('low', 'width')), ('Low width', 0.1, 8, 0.1, '')),
	('veq.mid_gain', 1.0, ('voiceEq', ('mid', 'gain')), ('Mid gain', -15, 15, 0.5, 'dB')),
	('veq.mid_freq', 3000.0, ('voiceEq', ('mid', 'frequency')), ('Mid frequency', 200, 4000, 10, 'Hz')),
	('veq.mid_width', 4.0, ('voiceEq', ('mid', 'width')), ('Mid width', 0.1, 8, 0.1, '')),
	('veq.high_gain', 1.0, ('voiceEq', ('high', 'gain')), ('High gain', -15, 15, 0.5, 'dB')),
	('veq.high_freq', 8000.0, ('voiceEq', ('high', 'frequency')), ('High frequency', 1500, 12000, 50, 'Hz')),
	('veq.high_width', 1.0, ('voiceEq', ('high', 'width')), ('High width', 0.1, 8, 0.1, '')),

	('des.enable', 0, ('deEsser', 'enabled'), None),
	('des.thresh', 0.0, ('deEsser', 'threshold'), ('Threshold', -30, 10, 0.5, 'dB')),
	('des.freq', 8000.0, ('deEsser', 'frequency'), ('Frequency', 2000, 12000, 50, 'Hz')),
	('des.ratio', 4.0, ('deEsser', 'ratio'), ('Ratio', 1, 20, 0.5, ':1')),
	('des.attack', 5.0, ('deEsser', 'attack'), ('Attack', 0.1, 100, 0.1, 'ms')),
	('des.release', 250.0, ('deEsser', 'release'), ('Release', 10, 1000, 10, 'ms')),

	('comp.enable', 0, ('compressor', 'enabled'), None),
	('comp.thresh', -20.0, ('compressor', 'threshold'), ('Threshold', -60, 0, 1, 'dB')),
	('comp.ratio', 4.0, ('compressor', 'ratio'), ('Ratio', 1, 30, 0.5, ':1')),
	('comp.makeup', 1.0, ('compressor', 'makeup'), ('Makeup gain', 0, 20, 0.5, 'dB')),
	('comp.attack', 5.0, ('compressor', 'attack'), ('Attack', 0.1, 200, 0.1, 'ms')),
	('comp.release', 250.0, ('compressor', 'release'), ('Release', 10, 2000, 10, 'ms')),

	('lim.boost', 1.0, ('limiter', 'boost'), ('Boost', 0, 24, 0.5, 'dB')),
	('lim.attack', 5.0, ('limiter', 'attack'), ('Attack', 0.1, 100, 0.1, 'ms')),
	('lim.release', 250.0, ('limiter', 'release'), ('Release', 10, 1000, 10, 'ms')),
]

# Linear-gain parameters, shown in dB in the UI.
LINEAR = {VOLUME, 'veq.low_gain', 'veq.mid_gain', 'veq.high_gain', 'comp.makeup', 'lim.boost'}

# UI sections in processing order: (prefix, title, hint, has an on/off switch)
SECTIONS = [
	('dpop', 'High-pass filter', 'Removes rumble, breath pops and desk thumps below the cutoff.', True),
	('nr', 'Noise reduction', 'Lowers steady background noise like fans and hum.', True),
	('exp', 'Noise gate', 'Turns the mic down when you are not talking.', True),
	('veq', 'Voice EQ', 'Three bands to shape the tone of your voice.', True),
	('des', 'De-esser', 'Softens harsh "s" and "sh" sounds.', True),
	('comp', 'Compressor', 'Evens out loud and quiet parts of your voice.', True),
	('lim', 'Limiter', 'Boosts your level and stops it from clipping.', False),
]

DEFAULTS = {name: default for name, default, _, _ in PARAMS}
FIELDS = {name: where for name, _, where, _ in PARAMS if where}
OUTPUT_PARAM = next((name, *ui) for name, _, _, ui in PARAMS if name == VOLUME)
# STAGES: [(prefix, title, hint, enable parameter or None, [(param, label, min, max, step, unit)])]
STAGES = [
	(prefix, title, hint, f'{prefix}.enable' if switch else None,
	 [(name, *ui) for name, _, _, ui in PARAMS if ui and name.split('.')[0] == prefix])
	for prefix, title, hint, switch in SECTIONS
]


def to_ui(param, value):
	"""APO value -> slider value."""
	if param in LINEAR:
		return round(20 * math.log10(value), 2) if value > 0 else -60.0
	return value


def from_ui(param, value):
	"""Slider value -> APO value."""
	if param in LINEAR:
		return round(10 ** (value / 20), 6)
	return value


def from_ghub(settings):
	"""APO parameters for one G HUB preset. Fields the preset leaves out fall back to DEFAULTS,
	which is what the APO does when G HUB doesn't set them."""
	p = dict(DEFAULTS)
	for name, (section, key) in FIELDS.items():
		node = settings if section is None else settings.get(section, {})
		if isinstance(key, tuple):
			node, key = node.get(key[0], {}), key[1]
		value = node.get(key)
		if value is None:
			continue
		p[name] = int(value) if isinstance(value, bool) else value
	return p


_ACRONYMS = {'AM', 'FM', 'TSM', 'G2'}


def pretty_name(key):
	"""BLUE_VOICE_PRESET_PRO_TSM_MYTH -> 'TSM Myth'."""
	words = key.removeprefix('BLUE_VOICE_PRESET_').removeprefix('PRO_').split('_')
	return ' '.join(w if w in _ACRONYMS else w.capitalize() for w in words if w)


def load_ghub_presets(path):
	"""[(key, display name, params)] in G HUB's order."""
	with open(path) as f:
		entries = json.load(f)['presets']
	out = []
	for entry in entries:
		bv = entry.get('blueVoiceSettings')
		if bv:
			key = bv['description']['name']
			out.append((key, pretty_name(key), from_ghub(bv['settings'])))
	return out


def params_text(params):
	"""The bridge's params file format."""
	return ''.join(f'{k} {params[k]}\n' for k in sorted(params))
