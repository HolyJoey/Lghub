import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import lightsync  # noqa: E402
import softlight  # noqa: E402

# Shaped like G HUB's keyframe files (made-up colours)
EFFECT = {'keyframeInfo': {'direction': 'CYCLE', 'speed': 100, 'keyframeMap': {
	'0': {'curveType': 'LINEAR', 'length': 10, 'lightingSlots': {'infoMap': {
		'PERKEY_KEYBOARD': {'perKeyMap': {'colorCodeMap': {'4': {'hex': '#000000'}}}}}}},
	'1': {'curveType': 'LINEAR', 'length': 10, 'lightingSlots': {'infoMap': {
		'PERKEY_KEYBOARD': {'perKeyMap': {'colorCodeMap': {'4': {'hex': '#ff0000'}}}}}}}}}}


class EchoTest(unittest.TestCase):
	def test_echo_and_keys(self):
		import keypress
		echo = softlight.EchoPress(['PERKEY_KEYBOARD:4'], echo=(200, 0, 0), rest=(0, 0, 0), speed=1000)
		echo.frame(0.0)
		echo.press('PERKEY_KEYBOARD:4')
		self.assertEqual(echo.frame(0.0)['PERKEY_KEYBOARD:4'], [200, 0, 0])
		self.assertEqual(echo.frame(1.5)['PERKEY_KEYBOARD:4'], [0, 0, 0])
		# a boot keyboard: modifiers as bits, then 6 usages
		desc = bytes([0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00,
		              0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x01,
		              0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65,
		              0x81, 0x00, 0xC0])
		fields = keypress.key_fields(desc)
		self.assertEqual(keypress.keys_down(fields, bytes([0x02, 0, 0x04, 0x1A, 0, 0, 0, 0])), {0xE1, 0x04, 0x1A})
		# a mouse: report 2, 16 buttons as bits
		mouse = bytes([0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x02, 0x05, 0x09, 0x19, 0x01, 0x29, 0x10, 0x15, 0x00,
		               0x25, 0x01, 0x95, 0x10, 0x75, 0x01, 0x81, 0x02, 0xC0])
		buttons = keypress.key_fields(mouse, keypress.BUTTON_PAGE)
		self.assertEqual(keypress.keys_down(buttons, bytes([2, 0b101, 0])), {1, 3})


class ZoneTargetTest(unittest.TestCase):
	def test_effect_on_zones(self):
		import hidpp
		import simulate
		fake = simulate.FakeRgbMouse()
		target = lightsync.make_target(hidpp.Device(fake), 'g502_x')
		self.assertTrue(target.zonal)
		self.assertEqual(target.keys, ['ZONE:0', 'ZONE:1'])
		cycle = softlight.ColorCycle(target.keys, speed=1000)
		target.send(cycle.frame(0.0))
		self.assertEqual(fake.set[0], (0, bytes([255, 0, 0, 2]).ljust(10, b'\0'), 0))   # fixed, not saved
		self.assertEqual(fake.set[1][1][:3], bytes([255, 0, 0]))


class CustomTest(unittest.TestCase):
	def test_save_and_play_back(self):
		import tempfile
		from unittest import mock
		with tempfile.TemporaryDirectory() as d, mock.patch.object(softlight, 'CUSTOM_DIR', d):
			frames = [(10, 'LINEAR', {'PERKEY_KEYBOARD:4': [0, 0, 0]}), (10, 'OUTQUAD', {'PERKEY_KEYBOARD:4': [255, 0, 0]})]
			file = softlight.save_custom('Red pulse!', frames, 'BOUNCE')
			self.assertEqual(file, 'red-pulse.json')
			self.assertEqual(softlight.custom_effects(), [('Red pulse!', 'red-pulse.json')])
			import json
			with open(os.path.join(d, file)) as f:
				back = softlight.parse_keyframes(json.load(f))
		self.assertEqual(back, ([(10, 'LINEAR', {'PERKEY_KEYBOARD:4': [0, 0, 0]}),
		                         (10, 'OUTQUAD', {'PERKEY_KEYBOARD:4': [255, 0, 0]})], 100, 'BOUNCE'))


class EasingTest(unittest.TestCase):
	def test_curves(self):
		for name in ('LINEAR', 'INQUAD', 'OUTCUBIC', 'INOUTSINE', 'OUTINEXPO', 'INCIRC', 'OUTBACK', 'INOUTBOUNCE',
		             'OUTINELASTIC'):
			f = softlight.easing(name)
			self.assertAlmostEqual(f(0), 0, places=2, msg=name)
			self.assertAlmostEqual(f(1), 1, places=2, msg=name)
		self.assertEqual(softlight.easing('NONE')(0.9), 0)
		self.assertLess(softlight.easing('INQUAD')(0.5), 0.5)


class KeyframesTest(unittest.TestCase):
	def test_play(self):
		frames, speed, direction = softlight.parse_keyframes(EFFECT)
		self.assertEqual((len(frames), speed, direction), (2, 100, 'CYCLE'))
		fx = softlight.Keyframes(frames, speed, direction)
		self.assertEqual(fx.frame(0.0), {'PERKEY_KEYBOARD:4': [0, 0, 0]})
		self.assertEqual(fx.frame(1.5), {'PERKEY_KEYBOARD:4': [128, 0, 0]})    # halfway into frame 1
		self.assertEqual(fx.frame(2.0), {'PERKEY_KEYBOARD:4': [255, 0, 0]})    # back towards frame 0

	def test_bounce(self):
		frames = [(1, 'LINEAR', {'k': [i, 0, 0]}) for i in range(3)]
		fx = softlight.Keyframes(frames, 1000, 'BOUNCE')
		order = [fx._next_index(0) for _ in range(5)]
		self.assertEqual(order, [1, 2, 1, 0, 1])


class ProceduralTest(unittest.TestCase):
	def test_starlight_and_cycle(self):
		keys = [f'PERKEY_KEYBOARD:{i}' for i in range(100)]
		star = softlight.Starlight(keys, count=40, speed=1000, rng=random.Random(1))
		star.frame(0.0)                                  # 40 stars start
		frame = star.frame(0.5)
		self.assertEqual(len(frame), 100)
		self.assertEqual(sum(c != [0, 0, 40] for c in frame.values()), 40)   # G HUB: star count at once
		self.assertIn(star.frame(1.0)['PERKEY_KEYBOARD:0'], ([255, 255, 255], [0, 0, 40]))
		cycle = softlight.ColorCycle(keys[:1], speed=1000)
		self.assertEqual(cycle.frame(0.0)[keys[0]], [255, 0, 0])
		self.assertEqual(cycle.frame(1.0)[keys[0]], [0, 255, 0])

	def test_ghub_sampler_regions(self):
		data = {'screen_sampler_info': {
			'region_map': {'a': {'top': 0.5, 'left': 0, 'right': 0.8, 'bottom': 0.2}},
			'lighting_slots': {'info_map': {'PERKEY_KEYBOARD': {'perKeyMap': {'colorCodeMap': {
				'4': {'tag': 'a'}, '5': {'tag': 'missing'}}}}}}}}
		regions, keys = lightsync.ghub_sampler(data)
		self.assertEqual([round(v, 6) for v in regions['a']], [0, 0.5, 0.2, 0.8])
		self.assertEqual(keys, {'PERKEY_KEYBOARD:4': 'a'})


if __name__ == '__main__':
	unittest.main()
