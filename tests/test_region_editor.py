import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import gi  # noqa: E402
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
import region_editor  # noqa: E402


class MoveTest(unittest.TestCase):
	def test_move_and_resize_stay_on_screen(self):
		r = [0.1, 0.5, 0.3, 0.8]
		self.assertEqual([round(v, 3) for v in region_editor.moved(r, 0.1, 0.0, False)], [0.2, 0.5, 0.4, 0.8])
		self.assertEqual([round(v, 3) for v in region_editor.moved(r, 1.0, 1.0, False)], [0.8, 0.7, 1.0, 1.0])
		self.assertEqual([round(v, 3) for v in region_editor.moved(r, -0.5, 0.0, True)], [0.1, 0.5, 0.13, 0.8])


if __name__ == '__main__':
	unittest.main()
