import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tray  # noqa: E402


class TrayMenuTest(unittest.TestCase):
	def test_items(self):
		items = tray.menu_items([('G502 HERO', None), ('G733', (35, 'Charging'))],
		                        [('voice', 'Blue VO!CE', True, None), ('eq', 'Equalizer', False, None)])
		labels = [p.get('label') for _i, p in items]
		self.assertEqual(labels, ['G502 HERO', 'G733 · 35 % (charging)', None, 'Blue VO!CE', 'Equalizer', None,
		                          'Open Lghub'])
		self.assertEqual(dict(items)[10]['toggle-state'], 1)
		self.assertEqual(dict(items)[11]['toggle-state'], 0)

	def test_no_devices(self):
		items = tray.menu_items([], [])
		self.assertEqual(items[0][1]['label'], 'No Logitech device connected')


if __name__ == '__main__':
	unittest.main()
