"""Effect parameter bytes as G HUB's get_raw_effect_params builds them (0x8070 / 0x8071)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import features  # noqa: E402


class EffectParamsTest(unittest.TestCase):
	def test_fixed_and_breathing(self):
		self.assertEqual(features.effect_params(features.FIXED, (1, 2, 3)), bytes([1, 2, 3, 2]) + bytes(6))
		self.assertEqual(features.effect_params(features.BREATHING, (1, 2, 3), 0x1388, 50),
		                 bytes([1, 2, 3, 0x13, 0x88, 0, 50, 0, 0, 0]))

	def test_color_wave_splits_the_period(self):
		self.assertEqual(features.effect_params(features.COLOR_WAVE, period=0x1388, brightness=80, direction=3),
		                 bytes([0, 0, 0, 0, 0, 0, 0x88, 3, 80, 0x13]))

	def test_signature_two_colors_and_style(self):
		self.assertEqual(features.effect_params(24, (0xFF, 0, 0xAB), 3000, 100, (0, 0xB8, 0xFC), style=2),
		                 bytes([0xFF, 0, 0xAB, 0, 0xB8, 0xFC, 0, 50, 100, 2]))
		self.assertEqual(features.effect_params(17, style=2)[9], 0)        # Pulsar Point has no style

	def test_names(self):
		self.assertEqual(features.EFFECTS[4], 'Color wave')
		self.assertEqual(features.STYLES[0], 'IMMERSE')


if __name__ == '__main__':
	unittest.main()
