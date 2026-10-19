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
		frame = star.frame(0.5)
		self.assertEqual(len(frame), 100)
		self.assertTrue(any(c != [0, 0, 40] for c in frame.values()))
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
