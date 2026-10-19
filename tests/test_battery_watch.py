import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import battery_watch  # noqa: E402


class BatteryWatchTest(unittest.TestCase):
	def test_warns_once_per_level(self):
		sent = []
		watch = battery_watch.Watch(send=lambda title, body: sent.append(title))
		mouse = mock.Mock(id='usb:1#1', name='G502')
		mouse.name = 'G502'
		for percent in (80, 31, 30, 25, 20, 15, 10, 9):
			watch.update(mouse, (percent, 'On battery'))
		self.assertEqual(sent, ['G502: battery low', 'G502: battery critical'])
		watch.update(mouse, (12, 'Charging'))          # charging: no warning, and it starts over
		watch.update(mouse, (60, 'On battery'))
		watch.update(mouse, (28, 'On battery'))
		self.assertEqual(sent[-1], 'G502: battery low')
		self.assertEqual(len(sent), 3)

	def test_levels(self):
		self.assertEqual([battery_watch.level(p) for p in (100, 31, 30, 16, 15, 0)],
		                 [None, None, 'low', 'low', 'critical', 'critical'])


if __name__ == '__main__':
	unittest.main()
