"""Blue VO!CE 2 presets: G HUB's own, from each device's depot (defaults_override.json, the
presets with attribute BLUE_VOICE_2_SETTINGS), fetched the first time the device shows up.

Settings keep G HUB's names (BlueVoice2.Settings in its microphone.proto, as the presets spell
them): the bridge's params file is a preset flattened to "noiseReduction.sensitivity 6" lines,
and bridge/bv2.c maps the names to the APO's property ids.
"""
import json
import os

# Devices G HUB ships Blue VO!CE 2 presets for (checked against every depot we know).
MODELS = ('g735', 'yeti_classic', 'yeti_nano', 'yeti_original_nano', 'yeti_x', 'yeti_x_wow')
DEPOT_FILE = 'defaults_override.json'
SKIP = {'volume', 'inputGain'}          # not DSP settings (see bv2.c)

# The sections G HUB's chain runs, in order, with the switch that turns each on.
SECTIONS = (('highPassFilter', 'High-pass filter'), ('noiseReduction', 'Noise reduction'),
            ('gatingCompressor', 'Noise gate'), ('gatingCompressor', 'Compressor'),
            ('multiBandEq', 'Equalizer'), ('dePopper', 'De-popper'), ('deEsser', 'De-esser'),
            ('hardLimiter', 'Limiter'))
SWITCHES = {'Noise gate': 'gatingCompressor.noiseGateEnabled',
            'Compressor': 'gatingCompressor.compressorEnabled'}


def switch_for(label):
	"""The setting that turns a section on, e.g. 'noiseReduction.enabled'."""
	section = next(s for s, name in SECTIONS if name == label)
	return SWITCHES.get(label, f'{section}.enabled')


def flatten(settings, prefix=''):
	"""G HUB's nested settings -> {"multiBandEq.lowBandFilter.gain": 4.0, ...}; switches as 0/1."""
	out = {}
	for key, value in settings.items():
		name = prefix + key
		if isinstance(value, dict):
			out.update(flatten(value, name + '.'))
		elif isinstance(value, bool):
			out[name] = 1 if value else 0
		elif isinstance(value, (int, float)) and key not in SKIP:
			out[name] = float(value)
	return out


def pretty_name(name):
	"""'08_BROADCASTER_1' -> 'Broadcaster 1', '42_High Voice - Loud' -> 'High Voice - Loud'."""
	head, sep, rest = name.partition('_')
	if sep and head.isdigit():
		name = rest
	words = name.replace('_', ' ').split()
	return ' '.join(w.capitalize() if w.isupper() and len(w) > 2 else w for w in words)


def load(path):
	"""[(id, display name, flat settings)] in G HUB's order, or [] if the file isn't there."""
	try:
		with open(path) as f:
			entries = json.load(f).get('presets', [])
	except (OSError, ValueError):
		return []
	out = []
	for entry in entries:
		bv = entry.get('blueVoice2Settings')
		if entry.get('attribute') == 'BLUE_VOICE_2_SETTINGS' and bv:
			out.append((entry['id'], pretty_name(entry.get('name', '')), flatten(bv.get('settings', {}))))
	return out


def params_text(settings, enabled=True):
	"""The bridge's params file (--engine bv2)."""
	lines = [f'enabled {1 if enabled else 0}\n']
	lines += [f'{k} {settings[k]:g}\n' for k in sorted(settings)]
	return ''.join(lines)


def path_for(data_dir, model):
	return os.path.join(data_dir, 'presets', f'{model}_bv2_presets.json')
