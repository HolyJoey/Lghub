"""Saved settings go back on when a device appears."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import features  # noqa: E402
import hidpp  # noqa: E402
import perkey  # noqa: E402
import restore  # noqa: E402
import simulate  # noqa: E402
import store  # noqa: E402


class RestoreTest(unittest.TestCase):
	def test_apply_saved(self):
		with tempfile.TemporaryDirectory() as d, mock.patch.object(store, 'CONFIG_DIR', d):
			self.assertFalse(restore.anything_saved())
			perkey.save_colors('g815', {'PERKEY_KEYBOARD:4': [255, 0, 0]})
			features.save_game_mode_keys('g815', [0xE3])
			self.assertTrue(restore.anything_saved())
			kb = simulate.FakeKeyboard()
			restore.apply_saved(hidpp.Device(kb), 'g815')
			self.assertEqual(kb.keys[1], (255, 0, 0))
			self.assertEqual(kb.disabled, {0xE3})


if __name__ == '__main__':
	unittest.main()
