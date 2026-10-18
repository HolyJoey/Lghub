"""Blue VO!CE presets and parameters.

Parameter names are the APO's own (see docs/apo-parameters.md). G HUB stores presets in its
*_device_presets.json files under different names; FIELDS maps one onto the other.
"""
import json
import math

# APO defaults (from dts_micopt_set's initialisation in the DLL). A parameter left out of the
# params file keeps this value, exactly as under G HUB.
DEFAULTS = {
	'micopt.enable': 1, 'micopt.meter_enable': 0, 'micopt.balance': 0.0, 'micopt.volume': 1.0,
	'dpop.enable': 0, 'dpop.freq': 80.0,
	'nr.enable': 0, 'nr.release': 75.0, 'nr.sensitivity': 25.0, 'nr.bias': 2.5, 'nr.attenuation_max': -20.0,
	'exp.enable': 0, 'exp.attack': 5.0, 'exp.release': 250.0, 'exp.hysteresis': 5.0, 'exp.ratio': 2.0,
	'exp.thresh': -48.0, 'exp.thresh_auto_enable': 0, 'exp.thresh_auto_sense': 20.0,
	'exp.attenuation_max': -20.0,
	'veq.enable': 0, 'veq.low_gain': 1.0, 'veq.low_freq': 250.0, 'veq.low_width': 1.0,
	'veq.mid_gain': 1.0, 'veq.mid_freq': 3000.0, 'veq.mid_width': 4.0,
	'veq.high_gain': 1.0, 'veq.high_freq': 8000.0, 'veq.high_width': 1.0,
	'des.enable': 0, 'des.attack': 5.0, 'des.release': 250.0, 'des.ratio': 4.0, 'des.thresh': 0.0,
	'des.freq': 8000.0,
	'comp.enable': 0, 'comp.attack': 5.0, 'comp.release': 250.0, 'comp.ratio': 4.0, 'comp.thresh': -20.0,
	'comp.makeup': 1.0,
	'lim.boost': 1.0, 'lim.attack': 5.0, 'lim.release': 250.0,
}

# APO parameter name -> (section, key) in G HUB's blueVoiceSettings.settings
FIELDS = {
	'micopt.balance': (None, 'balance'), 'micopt.volume': (None, 'volume'),
	'dpop.enable': ('dePopper', 'enabled'), 'dpop.freq': ('dePopper', 'frequency'),
	'nr.enable': ('noiseReduction', 'enabled'), 'nr.release': ('noiseReduction', 'release'),
	'nr.sensitivity': ('noiseReduction', 'sensitivity'), 'nr.bias': ('noiseReduction', 'bias'),
	'nr.attenuation_max': ('noiseReduction', 'attenuationMax'),
	'exp.enable': ('expander', 'enabled'), 'exp.attack': ('expander', 'attack'),
	'exp.release': ('expander', 'release'), 'exp.hysteresis': ('expander', 'hysteresis'),
	'exp.ratio': ('expander', 'ratio'), 'exp.thresh': ('expander', 'threshold'),
	'exp.thresh_auto_enable': ('expander', 'thresholdAutoEnabled'),
	'exp.thresh_auto_sense': ('expander', 'thresholdAutoSensibility'),
	'exp.attenuation_max': ('expander', 'attenuationMax'),
	'veq.enable': ('voiceEq', 'enabled'),
	'des.enable': ('deEsser', 'enabled'), 'des.attack': ('deEsser', 'attack'),
	'des.release': ('deEsser', 'release'), 'des.ratio': ('deEsser', 'ratio'),
	'des.thresh': ('deEsser', 'threshold'), 'des.freq': ('deEsser', 'frequency'),
	'comp.enable': ('compressor', 'enabled'), 'comp.attack': ('compressor', 'attack'),
	'comp.release': ('compressor', 'release'), 'comp.ratio': ('compressor', 'ratio'),
	'comp.thresh': ('compressor', 'threshold'), 'comp.makeup': ('compressor', 'makeup'),
	'lim.boost': ('limiter', 'boost'), 'lim.attack': ('limiter', 'attack'),
	'lim.release': ('limiter', 'release'),
}
for _band in ('low', 'mid', 'high'):
	for _apo, _key in (('gain', 'gain'), ('freq', 'frequency'), ('width', 'width')):
		FIELDS[f'veq.{_band}_{_apo}'] = ('voiceEq', (_band, _key))

# Linear-gain parameters, shown in dB in the UI.
LINEAR = {'micopt.volume', 'veq.low_gain', 'veq.mid_gain', 'veq.high_gain', 'comp.makeup', 'lim.boost'}

# UI layout: stage -> (title, hint, enable parameter, [(param, label, min, max, step, unit)]).
# Ranges cover every value the 22 G HUB presets use. Units 'dB' on LINEAR params are converted.
STAGES = [
	('dpop', 'High-pass filter', 'Removes rumble, breath pops and desk thumps below the cutoff.', 'dpop.enable', [
		('dpop.freq', 'Cutoff', 20, 300, 1, 'Hz'),
	]),
	('nr', 'Noise reduction', 'Lowers steady background noise like fans and hum.', 'nr.enable', [
		('nr.attenuation_max', 'Maximum reduction', -30, 0, 1, 'dB'),
		('nr.sensitivity', 'Sensitivity', 0, 30, 1, ''),
		('nr.bias', 'Bias', 0, 10, 0.1, ''),
		('nr.release', 'Release', 10, 1000, 5, 'ms'),
	]),
	('exp', 'Noise gate', 'Turns the mic down when you are not talking.', 'exp.enable', [
		('exp.thresh', 'Threshold', -80, 0, 1, 'dB'),
		('exp.ratio', 'Ratio', 1, 20, 0.5, ':1'),
		('exp.attenuation_max', 'Maximum reduction', -60, 0, 1, 'dB'),
		('exp.attack', 'Attack', 0.1, 100, 0.1, 'ms'),
		('exp.release', 'Release', 10, 2000, 10, 'ms'),
		('exp.hysteresis', 'Hysteresis', 0, 200, 1, 'ms'),
	]),
	('veq', 'Voice EQ', 'Three bands to shape the tone of your voice.', 'veq.enable', [
		('veq.low_gain', 'Low gain', -15, 15, 0.5, 'dB'),
		('veq.low_freq', 'Low frequency', 40, 600, 5, 'Hz'),
		('veq.low_width', 'Low width', 0.1, 8, 0.1, ''),
		('veq.mid_gain', 'Mid gain', -15, 15, 0.5, 'dB'),
		('veq.mid_freq', 'Mid frequency', 200, 4000, 10, 'Hz'),
		('veq.mid_width', 'Mid width', 0.1, 8, 0.1, ''),
		('veq.high_gain', 'High gain', -15, 15, 0.5, 'dB'),
		('veq.high_freq', 'High frequency', 1500, 12000, 50, 'Hz'),
		('veq.high_width', 'High width', 0.1, 8, 0.1, ''),
	]),
	('des', 'De-esser', 'Softens harsh "s" and "sh" sounds.', 'des.enable', [
		('des.thresh', 'Threshold', -30, 10, 0.5, 'dB'),
		('des.freq', 'Frequency', 2000, 12000, 50, 'Hz'),
		('des.ratio', 'Ratio', 1, 20, 0.5, ':1'),
		('des.attack', 'Attack', 0.1, 100, 0.1, 'ms'),
		('des.release', 'Release', 10, 1000, 10, 'ms'),
	]),
	('comp', 'Compressor', 'Evens out loud and quiet parts of your voice.', 'comp.enable', [
		('comp.thresh', 'Threshold', -60, 0, 1, 'dB'),
		('comp.ratio', 'Ratio', 1, 30, 0.5, ':1'),
		('comp.makeup', 'Makeup gain', 0, 20, 0.5, 'dB'),
		('comp.attack', 'Attack', 0.1, 200, 0.1, 'ms'),
		('comp.release', 'Release', 10, 2000, 10, 'ms'),
	]),
	('lim', 'Limiter', 'Boosts your level and stops it from clipping.', None, [
		('lim.boost', 'Boost', 0, 24, 0.5, 'dB'),
		('lim.attack', 'Attack', 0.1, 100, 0.1, 'ms'),
		('lim.release', 'Release', 10, 1000, 10, 'ms'),
	]),
]

OUTPUT_PARAM = ('micopt.volume', 'Output level', -30, 0, 0.5, 'dB')


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
	"""The host's params file format."""
	return ''.join(f'{k} {params[k]}\n' for k in sorted(params))
