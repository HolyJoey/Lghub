"""A mouse light strip (G502 X PLUS-like): its LEDs from G HUB's layout (circles), the light map's
LED numbers, and its own signature effect (lighting_effects.json)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hidpp  # noqa: E402
import perkey  # noqa: E402
import simulate  # noqa: E402
import softlight  # noqa: E402

METADATA = {'images': [{'key': 'device_image', 'origin': {'width': 1391, 'height': 2700},
                        'zones': [{'id': 'PERKEY_COSMETIC', 'components': [
                            {'id': 1, 'renderings': [{'type': 'circle', 'rect': {'x': 430, 'y': 1900, 'r': 310}}]},
                            {'id': 2, 'renderings': [{'type': 'circle', 'rect': {'x': 820, 'y': 2140, 'r': 240}}]}]}]}]}
LIGHT_MAP = {'zonal': {}, 'perKey': {'PERKEY_COSMETIC': {'mapping': {'1': {'ledIndex': 3}, '2': {'ledIndex': 7}}}}}
EFFECTS = {'effects': [{'name': 'SIGNATURE_FRAME_ACTIVE', 'keyframeInfo': {'speed': 2, 'direction': 'CYCLE', 'keyframeMap': {
	'0': {'curveType': 'LINEAR', 'length': 3, 'lightingSlots': {'infoMap': {'PERKEY_COSMETIC': {'perKeyMap': {
		'colorCodeMap': {'1': {'hex': '#00b8fb'}, '2': {'hex': '#fc01a9'}}}}}}}}}}]}


class LightStripTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		paths = {}
		for name, data in (('metadata', METADATA), ('light_map', LIGHT_MAP), ('effects', EFFECTS)):
			paths[name] = os.path.join(self.tmp.name, name + '.json')
			with open(paths[name], 'w') as f:
				json.dump(data, f)
		for target, name in (('depots.metadata_path', 'metadata'), ('depots.light_map_path', 'light_map'),
		                     ('depots.device_effects_path', 'effects')):
			p = mock.patch(target, return_value=paths[name])
			p.start()
			self.addCleanup(p.stop)

	def test_layout_reads_circle_leds(self):
		width, height, leds = perkey.load_layout('g502x_plus')
		self.assertEqual((width, height), (1391, 2700))
		self.assertEqual(leds[0], ('PERKEY_COSMETIC', 1, 120, 1590, 620, 620))     # centre and radius -> box

	def test_layout_reads_g_hubs_other_circle_format(self):
		import tempfile
		data = {'images': [{'origin': {'width': 100, 'height': 50}, 'zones': [{'id': 'PERKEY_COSMETIC_3', 'components': [
			{'id': 160, 'renderings': [{'type': 'circle', 'circle': {'cx': 60, 'cy': 30, 'r': 5}}]}]}]}]}
		with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
			json.dump(data, f)
		self.addCleanup(os.unlink, f.name)
		with mock.patch('depots.metadata_path', return_value=f.name):
			self.assertEqual(perkey.load_layout('g316x')[2], [('PERKEY_COSMETIC_3', 160, 55, 25, 10, 10)])

	def test_layout_skips_zone_drawings(self):
		import tempfile
		data = {'images': [{'origin': {'width': 100, 'height': 50}, 'zones': [{'id': 'ZONE_PRIMARY', 'components': [
			{'renderings': [{'type': 'rect', 'rect': {'x': 0, 'y': 0, 'width': 10, 'height': 10}}]}]}]}]}
		with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
			json.dump(data, f)
		self.addCleanup(os.unlink, f.name)
		with mock.patch('depots.metadata_path', return_value=f.name):
			self.assertEqual(perkey.load_layout('g502_hero'), (100, 50, []))

	def test_layout_reads_path_leds(self):
		import perkey
		self.assertEqual(perkey._path_box('M 10 10 l 5 0 l 0 5 Z'), (10.0, 10.0, 5.0, 5.0))
		self.assertEqual(perkey._path_box('m 1,2 h 3 v 4 z'), (1.0, 2.0, 3.0, 4.0))
		self.assertEqual(perkey._box({'type': 'path', 'd': 'M 0 0 C 0 10 10 10 10 0'}), (0.0, 0.0, 10.0, 10.0))

	def test_colours_go_through_the_light_map(self):
		fake = simulate.FakeMouseXPlus()
		colors = {'PERKEY_COSMETIC:1': [1, 2, 3], 'PERKEY_COSMETIC:2': [4, 5, 6]}
		perkey.apply(hidpp.Device(fake), colors, light_map=perkey.load_light_map('g502x_plus'))
		self.assertEqual(fake.keys, {3: (1, 2, 3), 7: (4, 5, 6)})                # LED 3 and 7, not 1 and 2

	def test_signature_effect(self):
		effects = softlight.device_effects('g502x_plus')
		self.assertEqual([name for name, _e in effects], ['SIGNATURE_FRAME_ACTIVE'])
		frames, _speed, direction = softlight.parse_keyframes(effects[0][1])
		self.assertEqual(direction, 'CYCLE')
		self.assertEqual(frames[0][2]['PERKEY_COSMETIC:1'], [0x00, 0xb8, 0xfb])
		with mock.patch('depots.device_effects_path', return_value=os.path.join(self.tmp.name, 'none.json')):
			self.assertEqual(softlight.device_effects('g502x'), [])


if __name__ == '__main__':
	unittest.main()
