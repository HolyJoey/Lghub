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


if __name__ == '__main__':
	unittest.main()
