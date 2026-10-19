"""Blue VO!CE 2: G HUB preset files to the bridge's params, and which mics get it."""
import json
import os
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
		self.assertEqual(presets[0][2], {'highPassFilter.enabled': 1, 'highPassFilter.frequency': 70.0,
		                                 'multiBandEq.enabled': 0, 'multiBandEq.lowBandFilter.frequency': 175.0,
		                                 'multiBandEq.lowBandFilter.gain': 4.0, 'multiBandEq.lowBandFilter.q': 1.0})

	def test_missing_file(self):
		self.assertEqual(bv2_presets.load(self.path + '.gone'), [])

	def test_params_text(self):
		text = bv2_presets.params_text({'noiseReduction.release': 250.0, 'deEsser.enabled': 1}, enabled=False)
		self.assertEqual(text, 'enabled 0\ndeEsser.enabled 1\nnoiseReduction.release 250\n')

	def test_switches(self):
		self.assertEqual(bv2_presets.switch_for('Noise gate'), 'gatingCompressor.noiseGateEnabled')
		self.assertEqual(bv2_presets.switch_for('Limiter'), 'hardLimiter.enabled')


class MicTest(unittest.TestCase):
	def test_matching(self):
		yeti = {'name': 'alsa_input.usb-Logitech_Yeti_X-00.analog-stereo', 'description': 'Yeti X Analog Stereo'}
		prox = {'name': 'alsa_input.usb-Logitech_PRO_X_000000000000-00.mono-fallback', 'description': 'PRO X'}
		self.assertTrue(pw.is_bv2_mic(yeti))
		self.assertFalse(pw.is_bv2_mic(prox))
		self.assertTrue(pw.is_blue_voice_headset(prox))

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
