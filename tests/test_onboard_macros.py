"""Keyboards' onboard macro library (tag 0x113, onboard_macros.py), in G HUB's byte layout."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import onboard_macros as om  # noqa: E402


class MacroLibraryTest(unittest.TestCase):
	def test_library_round_trip(self):
		steps = [(om.KEY_DOWN, bytes([0x02, 0x04])), (om.DELAY, bytes([0, 50])), (om.KEY_UP, bytes([0x02, 0x04]))]
		data = om.encode_steps(steps)
		self.assertEqual(data, bytes([0x43, 2, 4, 0x40, 0, 50, 0x44, 2, 4, 0xFF]))
		tag = om.encode_library([(7, 'Hi', data), (0x0102, 'x' * 30, b'\xff')])
		self.assertEqual(tag[:5], bytes([0, 7, 2]) + b'Hi')
		self.assertEqual(tag[5:7], bytes([0, len(data)]))
		lib = om.parse_library(tag)
		self.assertEqual(lib, [(7, 'Hi', data), (0x0102, 'x' * 24, b'\xff')])
		self.assertEqual(om.parse_steps(lib[0][2]), steps)

	def test_truncated_entry_stops(self):
		self.assertEqual(om.parse_library(bytes([0, 1, 30]) + b'abc'), [])
		self.assertEqual(om.parse_library(bytes([0, 1, 1]) + b'a' + bytes([0, 9, 1])), [])

	def test_end_marker_once(self):
		self.assertEqual(om.encode_steps([(0x20, b'\xff')]), bytes([0x20, 0xFF]))
		self.assertEqual(om.encode_steps([(0x20, b'\x01')]), bytes([0x20, 0x01, 0xFF]))

	def test_describe(self):
		names = {4: 'A'}
		self.assertEqual(om.describe((om.KEY_DOWN, bytes([0, 4])), names), 'A down')
		self.assertEqual(om.describe((om.DELAY, bytes([1, 0]))), 'wait 256 ms')
		self.assertEqual(om.describe((om.MOUSE_DOWN, bytes([0, 5]))), 'mouse button 1, 3 down')
		self.assertEqual(om.describe((om.MOUSE_MOVE, bytes([0xFF, 0xFE, 0, 3]))), 'move mouse -2, 3')
		self.assertEqual(om.describe((0x60, bytes(4))), 'step 0x60')


if __name__ == '__main__':
	unittest.main()
