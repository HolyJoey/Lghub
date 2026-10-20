"""Blue VO!CE 2: G HUB preset files to the bridge's params, and which mics get it."""
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import bv2_presets  # noqa: E402
import engine  # noqa: E402
import pw  # noqa: E402

# The shape of a device's defaults_override.json (values made up, names as G HUB spells them)
FILE = {'presets': [
	{'id': 'a', 'name': '08_BROADCASTER_1', 'attribute': 'BLUE_VOICE_2_SETTINGS', 'blueVoice2Settings': {
		'settings': {'highPassFilter': {'enabled': True, 'frequency': 70},
		             'multiBandEq': {'enabled': False, 'lowBandFilter': {'frequency': 175, 'gain': 4, 'q': 1}},
		             'inputGain': 0.48, 'inputGainCardId': 'x', 'volume': 0}}},
	{'id': 'b', 'name': 'ACOUSTICS', 'attribute': 'ACOUSTICS', 'acoustics': {}},
	{'id': 'c', 'name': '42_High Voice - Loud', 'attribute': 'BLUE_VOICE_2_SETTINGS',
	 'blueVoice2Settings': {'settings': {}}},
	{'id': 'd', 'name': '50_Robot', 'attribute': 'AUDIO_EFFECTS_SETTINGS', 'audioEffectsSettings': {
		'settings': {'vocalChanger': {'vocalMode1': 'VOCAL_MODE_ROBOT', 'voiceGain1': 1},
		             'delay': {'inputMode': 'INPUT_MODE_LEFT'}, 'reverb': {'enabled': True, 'mix': 0.5}}}},
]}


class PresetTest(unittest.TestCase):
	def setUp(self):
		fd, self.path = tempfile.mkstemp(suffix='.json')
		with os.fdopen(fd, 'w') as f:
			json.dump(FILE, f)

	def tearDown(self):
		os.unlink(self.path)

	def test_load(self):
		presets = bv2_presets.load(self.path)
		self.assertEqual([(i, n) for i, n, _ in presets], [('a', 'Broadcaster 1'), ('c', 'High Voice - Loud')])
		settings = presets[0][2]
		self.assertEqual(set(settings), set(bv2_presets.VOICE_NAMES) | {'inputGain'})   # every field, as G HUB sends them
		self.assertEqual(settings['inputGain'], 0.48)                                  # the mic's own gain
		self.assertEqual(settings['highPassFilter.frequency'], 70.0)
		self.assertEqual(settings['multiBandEq.lowBandFilter.gain'], 4.0)
		self.assertEqual(settings['gatingCompressor.noiseGateAttack'], 0)   # left out of the file = 0

	def test_effects(self):
		presets = bv2_presets.load(self.path, effects=True)
		self.assertEqual([(i, n) for i, n, _ in presets], [('d', 'Robot')])
		settings = presets[0][2]
		self.assertEqual(set(settings), set(bv2_presets.EFFECT_NAMES))
		self.assertEqual(settings['effects.vocalChanger.vocalMode1'], 4)        # VOCAL_MODE_ROBOT
		self.assertEqual(settings['effects.delay.inputMode'], 2)                # INPUT_MODE_LEFT
		self.assertEqual(settings['effects.reverb.mix'], 0.5)

	def test_names_match_bridge(self):
		with open(os.path.join(os.path.dirname(__file__), '..', 'bridge', 'bv2.c')) as f:
			bridge = set(re.findall(r'\{"([A-Za-z.0-9]+)", \d+\}', f.read()))
		self.assertEqual(bridge, set(bv2_presets.VOICE_NAMES) | set(bv2_presets.EFFECT_NAMES))

	def test_missing_file(self):
		self.assertEqual(bv2_presets.load(self.path + '.gone'), [])

	def test_params_text(self):
		text = bv2_presets.params_text({'noiseReduction.release': 250.0, 'deEsser.enabled': 1, 'inputGain': 0.5},
		                               enabled=False)
		self.assertEqual(text, 'enabled 0\ndeEsser.enabled 1\nnoiseReduction.release 250\n')

	def test_controls_cover_names(self):
		# every setting has a control on the page, and controls only use names the bridge knows
		used = set()
		for _title, switch, controls in bv2_presets.STAGES + bv2_presets.EFFECT_STAGES:
			used |= {switch} - {None} | {c[0] for c in controls}
		names = set(bv2_presets.VOICE_NAMES) | set(bv2_presets.EFFECT_NAMES)
		self.assertEqual(used - names, {bv2_presets.MIC_GAIN})
		self.assertEqual(names - used, set())
		self.assertEqual(bv2_presets.choices('SHAPE_MODE_')[0], (0, 'Sine'))


class MicTest(unittest.TestCase):
	def test_matching(self):
		yeti = {'name': 'alsa_input.usb-Logitech_Yeti_X-00.analog-stereo', 'description': 'Yeti X Analog Stereo'}
		prox = {'name': 'alsa_input.usb-Logitech_PRO_X_000000000000-00.mono-fallback', 'description': 'PRO X'}
		self.assertTrue(pw.is_bv2_mic(yeti))
		self.assertFalse(pw.is_bv2_mic(prox))
		self.assertTrue(pw.is_blue_voice_headset(prox))
		prox2 = {'name': 'alsa_input.usb-Logitech_PRO_X_2_LIGHTSPEED-00.mono-fallback', 'description': 'PRO X 2 LIGHTSPEED'}
		self.assertTrue(pw.is_bv2_mic(prox2))                        # Blue VO!CE 2, not the G Pro X's
		self.assertFalse(pw.is_blue_voice_headset(prox2))
		self.assertEqual(bv2_presets.depot_file('pro_x2_gaming_wireless_headset'),
		                 'pro_x2_wireless_headset_defaults_override.json')
		self.assertEqual(bv2_presets.depot_file('yeti_gx'), bv2_presets.DEPOT_FILE)

	def test_engine_kind(self):
		e = engine.Engine.__new__(engine.Engine)
		e.input = {'name': 'alsa_input.usb-Logitech_Yeti_Nano', 'description': 'Yeti Nano'}
		with mock.patch('os.path.exists', return_value=True):
			self.assertEqual(e.wanted_kind(), 'bv2')
		with mock.patch('os.path.exists', return_value=False):
			self.assertEqual(e.wanted_kind(), 'micopt')   # without the DLL, Blue VO!CE as before
		e.input = None
		self.assertEqual(e.wanted_kind(), 'micopt')


if __name__ == '__main__':
	unittest.main()
