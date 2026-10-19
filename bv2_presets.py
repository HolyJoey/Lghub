"""Blue VO!CE 2 presets: G HUB's own, from each device's depot (defaults_override.json, the
presets with attribute BLUE_VOICE_2_SETTINGS, and the voice effects with AUDIO_EFFECTS_SETTINGS),
fetched the first time the device shows up.

Settings keep G HUB's names (BlueVoice2.Settings and Effects.Settings in its microphone.proto, as
the presets spell them; effects under "effects."): the bridge's params file is a preset flattened
to "noiseReduction.sensitivity 6" lines, and bridge/bv2.c maps the names to the APO's property ids.
G HUB's preset files leave out fields that are 0 (protobuf JSON) but it sends every field to the
APO, so a preset here sets every name, 0 where the file has none.
"""
import json
import os

# Devices G HUB ships Blue VO!CE 2 presets for (checked against every depot we know).
MODELS = ('g735', 'yeti_classic', 'yeti_nano', 'yeti_original_nano', 'yeti_x', 'yeti_x_wow')
DEPOT_FILE = 'defaults_override.json'
SKIP = {'volume', 'inputGain'}          # not DSP settings (see bv2.c)

# Every setting the bridge knows (bridge/bv2.c's names table; tests/test_bv2.py keeps them equal).
VOICE_NAMES = (
	'highPassFilter.enabled', 'highPassFilter.frequency',
	'noiseReduction.enabled', 'noiseReduction.sensitivity', 'noiseReduction.bias',
	'noiseReduction.maxAttenuation', 'noiseReduction.release',
	'gatingCompressor.noiseGateEnabled', 'gatingCompressor.noiseGateThreshold',
	'gatingCompressor.noiseGateMaxAttenuation', 'gatingCompressor.noiseGateAttack',
	'gatingCompressor.noiseGateRelease', 'gatingCompressor.noiseGateHoldTime',
	'gatingCompressor.compressorEnabled', 'gatingCompressor.compressorThreshold',
	'gatingCompressor.compressorRatio', 'gatingCompressor.compressorPreGain',
	'gatingCompressor.compressorPostGain', 'gatingCompressor.compressorAttack',
	'gatingCompressor.compressorRelease',
	'multiBandEq.enabled',
	'multiBandEq.lowBandFilter.frequency', 'multiBandEq.lowBandFilter.gain', 'multiBandEq.lowBandFilter.q',
	'multiBandEq.midBandFilter.frequency', 'multiBandEq.midBandFilter.gain', 'multiBandEq.midBandFilter.q',
	'multiBandEq.highBandFilter.frequency', 'multiBandEq.highBandFilter.gain', 'multiBandEq.highBandFilter.q',
	'dePopper.enabled', 'dePopper.threshold', 'dePopper.frequency', 'dePopper.width',
	'dePopper.maxAttenuation', 'dePopper.attack', 'dePopper.release',
	'deEsser.enabled', 'deEsser.threshold', 'deEsser.frequency', 'deEsser.width',
	'deEsser.maxAttenuation', 'deEsser.attack', 'deEsser.release',
	'hardLimiter.enabled', 'hardLimiter.attack', 'hardLimiter.release', 'hardLimiter.boost',
)
EFFECT_NAMES = tuple('effects.' + n for n in (
	'vocalChanger.vocalMode1', 'vocalChanger.voiceModFactor1', 'vocalChanger.vocalMode2',
	'vocalChanger.voiceModFactor2', 'vocalChanger.voiceGain1', 'vocalChanger.voiceGain2',
	'vocalChanger.chorusEnabled', 'vocalChanger.chorusDelay', 'vocalChanger.chorusDelayMod',
	'vocalChanger.chorusDelayModRate', 'vocalChanger.chorusPitchMod', 'vocalChanger.chorusPitchModRate',
	'flangerPhaser.enabled', 'flangerPhaser.phaserMode', 'flangerPhaser.depth', 'flangerPhaser.rate',
	'ringModulation.enabled', 'ringModulation.mix', 'ringModulation.shapeMode', 'ringModulation.carrierFrequency',
	'reverb.enabled', 'reverb.earlyLateMix', 'reverb.reflectionMode', 'reverb.reflectionLowPassFrequency',
	'reverb.roomSize', 'reverb.mix',
	'delay.enabled', 'delay.inputMode', 'delay.feedbackMode', 'delay.feedbackTimbre', 'delay.leftDelay',
	'delay.rightDelay', 'delay.feedback', 'delay.mix'))

# The effects' enums (microphone.proto), as the preset files spell them -> their numbers.
_ENUMS = {
	'VOCAL_MODE_': ('OFF', 'FORMANT_WARP', 'PITCH_SHIFT', 'FORMANT_SHIFT', 'ROBOT', 'WHISPEZ', 'NOICE', 'GROWL',
	                'AIR', 'ETHER', 'HOUSEOTRON', 'FUNKBOT', 'TALKBOX', 'SUBBY', 'NO_TREBLE'),
	'PHASER_MODE_': ('FLANGER_UP', 'FLANGER_DOWN', 'FLANGER_OSCILLATE', 'PHASER_STUN', 'PHASER_HEAVY',
	                 'PHASER_KILL'),
	'SHAPE_MODE_': ('SINE', 'TRIANGLE', 'SAW_TOOTH', 'SQUARE', 'HALFWAVERECTIFIER'),
	'REFLECTION_MODE_': ('NONE', 'TIGHT', 'MIDMIX', 'LARGEDIFF', 'ECHO', 'ECHO2', 'ECHO3', 'FLUTTER',
	                     'ST_FLUTTER', 'ECHO_FLUTTER'),
	'FEEDBACK_MODE_': ('NORMAL', 'CROSSED'),
	'FEEDBACK_TIMBRE_': ('FULL', 'DARK', 'BRIGHT'),
	'INPUT_MODE_': ('NORMAL', 'CROSSED', 'LEFT', 'RIGHT'),
}
ENUM_VALUES = {prefix + name: i for prefix, names in _ENUMS.items() for i, name in enumerate(names)}


# G HUB's Blue VO!CE 2 controls (its app's microphone settings panel): per stage, the switch that
# turns it on and its sliders as (setting, label, low, high, step, unit), ranges as G HUB has them.
def _eq_band(band, label, low, high, step):
	return ((f'multiBandEq.{band}.frequency', f'{label} frequency', low, high, step, 'Hz'),
	        (f'multiBandEq.{band}.gain', f'{label} gain', -12, 12, 0.5, 'dB'),
	        (f'multiBandEq.{band}.q', f'{label} width', 0.5, 10, 0.5, 'Q'))


STAGES = (
	('High-pass filter', 'highPassFilter.enabled', (
		('highPassFilter.frequency', 'Frequency', 20, 400, 1, 'Hz'),)),
	('Noise reduction', 'noiseReduction.enabled', (
		('noiseReduction.sensitivity', 'Sensitivity', 0, 40, 1, 'dB'),
		('noiseReduction.bias', 'Bias', 0, 5, 0.25, 'dB'),
		('noiseReduction.release', 'Release', 0, 1000, 5, 'ms'),
		('noiseReduction.maxAttenuation', 'Maximum attenuation', -60, 0, 1, 'dB'))),
	('Noise gate', 'gatingCompressor.noiseGateEnabled', (
		('gatingCompressor.noiseGateThreshold', 'Threshold', -80, -6, 1, 'dB'),
		('gatingCompressor.noiseGateAttack', 'Attack', 0, 200, 5, 'ms'),
		('gatingCompressor.noiseGateMaxAttenuation', 'Maximum attenuation', -60, 0, 1, 'dB'),
		('gatingCompressor.noiseGateHoldTime', 'Hold time', 0, 200, 5, 'ms'),
		('gatingCompressor.noiseGateRelease', 'Release', 50, 1000, 10, 'ms'))),
	('Compressor', 'gatingCompressor.compressorEnabled', (
		('gatingCompressor.compressorThreshold', 'Threshold', -40, 0, 1, 'dB'),
		('gatingCompressor.compressorPreGain', 'Pre-gain', -12, 12, 1, 'dB'),
		('gatingCompressor.compressorAttack', 'Attack', 0, 200, 5, 'ms'),
		('gatingCompressor.compressorRatio', 'Ratio', 1, 20, 1, ':1'),
		('gatingCompressor.compressorRelease', 'Release', 50, 1000, 10, 'ms'),
		('gatingCompressor.compressorPostGain', 'Post-gain', -12, 12, 1, 'dB'))),
	('Equalizer', 'multiBandEq.enabled',
		_eq_band('lowBandFilter', 'Low', 5, 500, 25) + _eq_band('midBandFilter', 'Mid', 400, 5000, 50)
		+ _eq_band('highBandFilter', 'High', 1000, 12000, 50)),
	('De-popper', 'dePopper.enabled', (
		('dePopper.threshold', 'Threshold', -50, 0, 1, 'dB'),
		('dePopper.attack', 'Attack', 0, 200, 1, 'ms'),
		('dePopper.frequency', 'Frequency', 60, 1000, 10, 'Hz'),
		('dePopper.release', 'Release', 20, 1000, 10, 'ms'),
		('dePopper.width', 'Width', 0.25, 20, 0.25, 'Q'),
		('dePopper.maxAttenuation', 'Maximum attenuation', -60, 0, 1, 'dB'))),
	('De-esser', 'deEsser.enabled', (
		('deEsser.threshold', 'Threshold', -50, 0, 1, 'dB'),
		('deEsser.attack', 'Attack', 0, 200, 1, 'ms'),
		('deEsser.frequency', 'Frequency', 1000, 10000, 50, 'Hz'),
		('deEsser.release', 'Release', 20, 1000, 10, 'ms'),
		('deEsser.width', 'Width', 0.25, 20, 0.25, 'Q'),
		('deEsser.maxAttenuation', 'Maximum attenuation', -60, 0, 1, 'dB'))),
	('Limiter', 'hardLimiter.enabled', (
		('hardLimiter.boost', 'Boost', -20, 20, 1, 'dB'),
		('hardLimiter.attack', 'Attack', 0, 10, 0.1, 'ms'),
		('hardLimiter.release', 'Release', 10, 500, 5, 'ms'))),
)

# The voice effects, the same way; a choice is (setting, label, enum prefix) with G HUB's names.
EFFECT_STAGES = (
	('Voice changer', None, (
		('effects.vocalChanger.vocalMode1', 'Primary voice', 'VOCAL_MODE_'),
		('effects.vocalChanger.voiceModFactor1', 'Primary factor', -2400, 2400, 50, 'cents'),
		('effects.vocalChanger.voiceGain1', 'Primary gain', -60, 0, 1, 'dB'),
		('effects.vocalChanger.vocalMode2', 'Secondary voice', 'VOCAL_MODE_'),
		('effects.vocalChanger.voiceModFactor2', 'Secondary factor', -2400, 2400, 50, 'cents'),
		('effects.vocalChanger.voiceGain2', 'Secondary gain', -60, 0, 1, 'dB'))),
	('Chorus', 'effects.vocalChanger.chorusEnabled', (
		('effects.vocalChanger.chorusDelay', 'Delay', 0, 100, 1, 'ms'),
		('effects.vocalChanger.chorusDelayMod', 'Delay modulation', 0, 100, 1, 'ms'),
		('effects.vocalChanger.chorusDelayModRate', 'Delay modulation rate', 0, 2, 0.05, 'Hz'),
		('effects.vocalChanger.chorusPitchMod', 'Pitch modulation', -600, 600, 10, 'cents'),
		('effects.vocalChanger.chorusPitchModRate', 'Pitch modulation rate', 0, 2, 0.05, 'Hz'))),
	('Flanger / phaser', 'effects.flangerPhaser.enabled', (
		('effects.flangerPhaser.phaserMode', 'Mode', 'PHASER_MODE_'),
		('effects.flangerPhaser.depth', 'Depth', 0, 1, 0.05, ''),
		('effects.flangerPhaser.rate', 'Rate', 0, 5, 0.1, 'Hz'))),
	('Reverb', 'effects.reverb.enabled', (
		('effects.reverb.reflectionMode', 'Reflections', 'REFLECTION_MODE_'),
		('effects.reverb.mix', 'Mix', 0, 1, 0.05, ''),
		('effects.reverb.reflectionLowPassFrequency', 'Reflection low-pass', 10, 10000, 20, 'Hz'),
		('effects.reverb.earlyLateMix', 'Early/late mix', 0, 1, 0.05, ''),
		('effects.reverb.roomSize', 'Room size', 0.01, 1, 0.05, ''))),
	('Delay', 'effects.delay.enabled', (
		('effects.delay.inputMode', 'Input', 'INPUT_MODE_'),
		('effects.delay.feedbackMode', 'Feedback mode', 'FEEDBACK_MODE_'),
		('effects.delay.feedbackTimbre', 'Feedback timbre', 'FEEDBACK_TIMBRE_'),
		('effects.delay.feedback', 'Feedback', 0, 0.6, 0.05, ''),
		('effects.delay.mix', 'Mix', 0, 1, 0.05, ''),
		('effects.delay.leftDelay', 'Left delay', 10, 2000, 10, 'ms'),
		('effects.delay.rightDelay', 'Right delay', 10, 2000, 10, 'ms'))),
	('Ring modulator', 'effects.ringModulation.enabled', (
		('effects.ringModulation.shapeMode', 'Shape', 'SHAPE_MODE_'),
		('effects.ringModulation.carrierFrequency', 'Frequency', 1, 2000, 10, 'Hz'),
		('effects.ringModulation.mix', 'Mix', 0, 1, 0.05, ''))),
)


def choices(prefix):
	"""[(number, label)] of an effects enum, e.g. 'VOCAL_MODE_' -> [(0, 'Off'), (1, 'Formant warp'), ...]."""
	return [(i, name.replace('_', ' ').capitalize()) for i, name in enumerate(_ENUMS[prefix])]


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
		elif isinstance(value, str) and value in ENUM_VALUES:
			out[name] = ENUM_VALUES[value]
	return out


def complete(settings, names):
	"""Every name in names: the preset's value, else 0 (what G HUB sends for a field it lacks)."""
	return {n: settings.get(n, 0) for n in names}


def pretty_name(name):
	"""'08_BROADCASTER_1' -> 'Broadcaster 1', '42_High Voice - Loud' -> 'High Voice - Loud'."""
	head, sep, rest = name.partition('_')
	if sep and head.isdigit():
		name = rest
	words = name.replace('_', ' ').split()
	return ' '.join(w.capitalize() if w.isupper() and len(w) > 2 else w for w in words)


def load(path, effects=False):
	"""[(id, display name, settings)] in G HUB's order, every name set (see complete()): the voice
	presets, or with effects=True the voice effects. [] if the file isn't there."""
	attribute, key, prefix, names = (('AUDIO_EFFECTS_SETTINGS', 'audioEffectsSettings', 'effects.', EFFECT_NAMES)
	                                 if effects else ('BLUE_VOICE_2_SETTINGS', 'blueVoice2Settings', '', VOICE_NAMES))
	try:
		with open(path) as f:
			entries = json.load(f).get('presets', [])
	except (OSError, ValueError):
		return []
	out = []
	for entry in entries:
		body = entry.get(key)
		if entry.get('attribute') == attribute and body:
			settings = complete(flatten(body.get('settings', {}), prefix), names)
			out.append((entry['id'], pretty_name(entry.get('name', '')), settings))
	return out


def params_text(settings, enabled=True):
	"""The bridge's params file (--engine bv2)."""
	lines = [f'enabled {1 if enabled else 0}\n']
	lines += [f'{k} {settings[k]:g}\n' for k in sorted(settings)]
	return ''.join(lines)


def path_for(data_dir, model):
	return os.path.join(data_dir, 'presets', f'{model}_bv2_presets.json')
