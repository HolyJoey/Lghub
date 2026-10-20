"""Reading key presses from a keyboard's own reports (Echo press)."""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import keypress  # noqa: E402

# A boot keyboard: modifiers as bits, then 6 usages (no report id)
BOOT = bytes([0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00,
              0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x01,
              0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65,
              0x81, 0x00, 0xC0])


class KeypressTest(unittest.TestCase):
	def test_rollover_errors_and_other_reports(self):
		fields = keypress.key_fields(BOOT)
		self.assertEqual(keypress.keys_down(fields, bytes([0, 0, 1, 1, 1, 1, 1, 1])), set())   # rollover error
		consumer = {3: [('array', 0, 16, 1, 1)]}
		self.assertEqual(keypress.keys_down(consumer, bytes([3, 0xE9, 0])), {0xE9})
		self.assertIsNone(keypress.keys_down(consumer, bytes([4, 1, 0])))

	def test_key_nodes_match_the_usb_port(self):
		with tempfile.TemporaryDirectory() as root:
			for name, port, desc in (('hidraw3', '1-2', BOOT), ('hidraw4', '1-3', BOOT), ('hidraw5', '1-2', b'')):
				dev = os.path.join(root, 'devices', port + ':1.0', name)
				os.makedirs(dev)
				with open(os.path.join(dev, 'report_descriptor'), 'wb') as f:
					f.write(desc)
				os.makedirs(os.path.join(root, 'class', name))
				os.symlink(dev, os.path.join(root, 'class', name, 'device'))
			with mock.patch('surface_tuning.SYS_HIDRAW', os.path.join(root, 'class')):
				found = keypress.key_nodes('1-2')
		self.assertEqual([path for path, _f in found], ['/dev/hidraw3'])
		with mock.patch('surface_tuning.SYS_HIDRAW', '/nonexistent'):
			self.assertEqual(keypress.key_nodes('1-2'), [])

	def test_keys_reports_each_new_press_once(self):
		read_end, write_end = os.pipe()
		pressed, done = [], threading.Event()

		def on_press(usage):
			pressed.append(usage)
			if len(pressed) == 2:
				done.set()

		keys = keypress.Keys([(f'/dev/fd/{read_end}', keypress.key_fields(BOOT))], on_press)
		keys.start()
		for report in (bytes([0, 0, 4, 0, 0, 0, 0, 0]), bytes([0, 0, 4, 5, 0, 0, 0, 0]), bytes([0, 0, 0, 0, 0, 0, 0, 0])):
			os.write(write_end, report)
			threading.Event().wait(0.02)
		done.wait(2)
		keys.stop()
		os.close(write_end)
		os.close(read_end)
		self.assertEqual(pressed, [4, 5])          # 4 held while 5 went down: reported once

	def test_keys_need_a_node(self):
		keys = keypress.Keys([('/nonexistent/hidraw', {})], print)
		with self.assertRaises(OSError):
			keys.start()


if __name__ == '__main__':
	unittest.main()
