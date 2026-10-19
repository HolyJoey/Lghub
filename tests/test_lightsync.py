"""LIGHTSYNC audio visualizer: bands from sound, and the keyboard frame built from them."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import lightsync  # noqa: E402


class VisualizerTest(unittest.TestCase):
	def test_bands_follow_the_sound(self):
		freqs = lightsync.band_freqs()
		bass = [0.5 * math.sin(2 * math.pi * freqs[0] * i / lightsync.RATE) for i in range(lightsync.FRAME)]
		levels = lightsync.band_levels(bass, freqs)
		self.assertEqual(levels.index(max(levels)), 0)
		self.assertLess(levels[-1], levels[0] - 0.3)
		self.assertEqual(lightsync.band_levels([0.0] * lightsync.FRAME, freqs), [0.0] * len(freqs))

	def test_frame(self):
		layout = (100, 100, [('PERKEY_KEYBOARD', 4, 0, 80, 10, 10),     # bottom left
		                     ('PERKEY_KEYBOARD', 5, 0, 0, 10, 10),      # top left
		                     ('PERKEY_KEYBOARD', 6, 90, 80, 10, 10),    # bottom right
		                     ('PERKEY_GKEY', 1, 0, 0, 10, 10)])
		frame = lightsync.frame_colors(layout, [0.5, 0, 0, 0, 0, 0, 0, 0], [200, 100, 0])
		self.assertEqual(frame['PERKEY_KEYBOARD:4'], [200, 100, 0])   # bass loud, low key lit
		self.assertNotEqual(frame['PERKEY_KEYBOARD:5'], [200, 100, 0])  # but not the top one
		self.assertNotEqual(frame['PERKEY_KEYBOARD:6'], [200, 100, 0])  # treble quiet
		self.assertNotIn('PERKEY_GKEY:1', frame)


class RunnerTest(unittest.TestCase):
	def test_switching_off_puts_the_colours_back(self):
		import tempfile
		from unittest import mock

		import hidpp
		import perkey
		import simulate
		import store
		with tempfile.TemporaryDirectory() as d, mock.patch.object(store, 'CONFIG_DIR', d), \
				mock.patch.object(lightsync, 'FILE', os.path.join(d, 'lightsync.json')):
			perkey.save_colors('g815', {'PERKEY_KEYBOARD:4': [9, 8, 7]})
			kb = simulate.FakeKeyboard()
			stopped = []
			visualizer = mock.Mock(dev=hidpp.Device(kb), stop=lambda: stopped.append(True))
			device = mock.Mock(id='usb:1', model=mock.Mock(key='g815'))
			runner = lightsync.Runner()
			runner.running['usb:1'] = (visualizer, {'effect': 'audio'})
			runner._maybe_stop('usb:1', device, {})          # the effect was switched off
			self.assertEqual(stopped, [True])
			self.assertEqual(kb.keys[1], (9, 8, 7))
			self.assertEqual(runner.running, {})


class GhubVisualizerTest(unittest.TestCase):
	def test_columns_light_from_the_bottom(self):
		data = {'audioVisualizerInfo': {'frequencyLayout': [
			{'range': {'start': 'LOW_60HZ', 'end': 'LOW_170HZ'}, 'slots': [
				{'lightingType': 'PER_KEY', 'perKeyType': 'PERKEY_KEYBOARD', 'slotCode': 224},
				{'lightingType': 'INVALID_LIGHTING', 'perKeyType': 'PERKEY_KEYBOARD'},
				{'lightingType': 'PER_KEY', 'perKeyType': 'PERKEY_KEYBOARD', 'slotCode': 4},
				{'lightingType': 'PER_KEY', 'perKeyType': 'PERKEY_KEYBOARD', 'slotCode': 20}]}]}}
		cols = lightsync.ghub_columns(data)
		self.assertEqual(cols, [(60, 170, ['PERKEY_KEYBOARD:224', None, 'PERKEY_KEYBOARD:4', 'PERKEY_KEYBOARD:20'])])
		present = {'PERKEY_KEYBOARD:224', 'PERKEY_KEYBOARD:4', 'PERKEY_KEYBOARD:20'}
		frame = lightsync.column_frame(cols, lambda lo, hi: 0.75, [100, 100, 100], present)
		self.assertEqual(frame['PERKEY_KEYBOARD:4'], [100, 100, 100])         # 3 of 4 slots lit
		self.assertEqual(frame['PERKEY_KEYBOARD:20'], [8, 8, 8])


class AudioOptionsTest(unittest.TestCase):
	def test_shape_levels(self):
		state = {}
		opts = {'adaptive': False, 'max_amplitude': 50, 'bass_noise': 20, 'boost': 0}
		self.assertEqual(lightsync.shape_levels([0.1, 0.4], [100, 1000], opts, state), [0.0, 0.8])
		self.assertEqual(lightsync.shape_levels([0.3], [1000], {'adaptive': False, 'boost': 100}, {}), [0.6])

	def test_colour_modes(self):
		cols = [(60, 170, ['a', 'b'])]
		reactive = lightsync.column_frame(cols, lambda lo, hi: 1.0, [0, 0, 0], {'a', 'b'}, mode='reactive',
		                                  high=[200, 0, 0])
		self.assertEqual(reactive['b'], [200, 0, 0])
		gradient = lightsync.column_frame(cols, lambda lo, hi: 1.0, [0, 0, 0], {'a', 'b'}, mode='gradient',
		                                  high=[200, 0, 0])
		self.assertEqual((gradient['a'], gradient['b']), ([0, 0, 0], [200, 0, 0]))
		dark = lightsync.column_frame(cols, lambda lo, hi: 0.0, [100, 0, 0], {'a', 'b'}, background=[0, 0, 9])
		self.assertEqual(dark['a'], [0, 0, 9])


class ScreenSamplerTest(unittest.TestCase):
	def test_regions_and_keys(self):
		# 6x6 picture: left third red, right third blue, middle green
		row = ([255, 0, 0] * 2 + [0, 255, 0] * 2 + [0, 0, 255] * 2)
		ppm = b'P6\n6 6\n255\n' + bytes(row * 6)
		colors = lightsync.region_colors(*lightsync.parse_ppm(ppm), step=1)
		self.assertEqual(colors['TOP_LEFT'], [255, 0, 0])
		self.assertEqual(colors['MID_RIGHT'], [0, 0, 255])
		self.assertEqual(colors['BOTTOM_CENTER'], [0, 255, 0])
		layout = (90, 90, [('PERKEY_KEYBOARD', 4, 0, 0, 10, 10), ('PERKEY_KEYBOARD', 5, 40, 40, 10, 10),
		                   ('PERKEY_KEYBOARD', 6, 80, 80, 10, 10)])
		frame = lightsync.sampler_frame(layout, colors)
		self.assertEqual(frame, {'PERKEY_KEYBOARD:4': [255, 0, 0], 'PERKEY_KEYBOARD:5': [0, 255, 0],
		                         'PERKEY_KEYBOARD:6': [0, 0, 255]})

	def test_boost(self):
		self.assertEqual(lightsync.boost([100, 100, 100], 3), [100, 100, 100])   # grey stays grey
		self.assertEqual(lightsync.boost([150, 100, 50], 0), [150, 100, 50])
		self.assertEqual(lightsync.boost([150, 100, 50], 1), [200, 100, 0])


if __name__ == '__main__':
	unittest.main()
