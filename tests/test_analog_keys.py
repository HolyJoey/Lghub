"""Analog keyboards' per-key settings: control indexes named from G HUB's layout (analog_keys.py),
the per-key tag format, and onboard-profile writes staying off (device_settings.py)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import analog_keys  # noqa: E402
import device_settings  # noqa: E402

LAYOUT = {'images': [{'origin': {'width': 300, 'height': 100}, 'zones': [{'id': 'PERKEY_KEYBOARD', 'components': [
	{'id': 26, 'renderings': [{'type': 'rect', 'rect': {'x': 0, 'y': 0, 'width': 100, 'height': 100}}]},
	{'id': 4, 'renderings': [{'type': 'rect', 'rect': {'x': 100, 'y': 0, 'width': 100, 'height': 100}}]}]}],
	'inputRegions': [
		{'inputs': [{'cid': 332}], 'renderings': [{'type': 'rect', 'rect': {'x': 5, 'y': 5, 'width': 90, 'height': 90}}]},
		{'inputs': [{'cid': 246}], 'renderings': [{'type': 'rect', 'rect': {'x': 105, 'y': 5, 'width': 90, 'height': 90}}]}]}]}


class AnalogKeysTest(unittest.TestCase):
	def setUp(self):
		with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
			json.dump(LAYOUT, f)
		self.addCleanup(os.unlink, f.name)
		p = mock.patch('depots.metadata_path', return_value=f.name)
		p.start()
		self.addCleanup(p.stop)

	def test_controls_named_after_the_key_drawn_there(self):
		self.assertEqual(analog_keys.cid_names('kb'), {332: 'W', 246: 'A'})

	def test_per_key_rows(self):
		profile = {'keys': {0: 1.2}, 'rapid': {1: 0.3}}
		self.assertEqual(analog_keys.per_key_rows(profile, [332, 246], 'kb'), [('W', 1.2, None), ('A', None, 0.3)])
		self.assertEqual(analog_keys.per_key_rows({'keys': {5: 2.0}}, [332], 'kb'), [('Control 5', 2.0, None)])

	def test_tag_bytes_match_the_read_format(self):
		data = device_settings.actuation_tag({1: 1.5, 0: 0.25})
		self.assertEqual(data, bytes([0, 0, 25, 1, 0, 150]))

	def test_profile_writes_stay_off(self):
		dev = mock.Mock()
		with self.assertRaises(OSError):
			device_settings.write_profile_tag(dev, device_settings.KEY_ACTUATION, b'\0\0\1')
		dev.call.assert_not_called()


if __name__ == '__main__':
	unittest.main()
