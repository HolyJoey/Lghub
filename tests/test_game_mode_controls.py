"""Game mode on the newer keyboards (0x4523): G HUB's bitmap of control indexes (features.py) and
the keys Lghub offers there, matched through the control list (hidpp_panel.game_mode_controls)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import features  # noqa: E402


class DisableControlsTest(unittest.TestCase):
	def test_bitmap_as_g_hub(self):
		bitmap = features.disabled_controls_bitmap([0, 9, 127, 200])
		self.assertEqual(len(bitmap), 16)
		self.assertEqual((bitmap[0], bitmap[1], bitmap[15]), (0x01, 0x02, 0x80))
		self.assertEqual(sum(bitmap), 0x83)

	def test_apply_maps_cids_to_indexes(self):
		calls = []

		class Dev:
			def has(self, feature):
				return feature in (features.DISABLE_CONTROLS, features.CONTROL_LIST)

			def call(self, feature, fn, params=b''):
				calls.append((feature, fn, bytes(params)))
				if feature == features.CONTROL_LIST:
					return bytes([3]) if fn == 0 else bytes([0, 10, 0, 20, 0, 30]).ljust(16, b'\0')
				return bytes(16)
		features.apply_game_mode(Dev(), [30, 10, 99])
		self.assertEqual(calls[-1], (features.DISABLE_CONTROLS, 0, features.disabled_controls_bitmap([2, 0])))

	def test_fkc_switch_as_g_hub(self):
		calls = []

		class Dev:
			def call(self, feature, fn, params=b''):
				calls.append((feature, fn, bytes(params)))
				return bytes([1]).ljust(16, b'\0')
		self.assertTrue(features.fkc_enabled(Dev()))
		features.set_fkc_enabled(Dev(), False)
		self.assertEqual(calls, [(0x1B05, 1, bytes([0, 0])), (0x1B05, 1, bytes([1, 0]))])

	def test_offered_keys(self):
		try:
			import hidpp_panel
		except (ImportError, ValueError):
			self.skipTest('GTK not available')
		with mock.patch('analog_keys.cid_usages', return_value={10: 0xE3, 20: 0x04, 30: 0x39}):
			self.assertEqual(hidpp_panel.game_mode_controls([10, 20, 30], 'kb'),
			                 [(10, 'Left Windows'), (30, 'Caps Lock')])


if __name__ == '__main__':
	unittest.main()
