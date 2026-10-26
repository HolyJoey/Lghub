"""Keyboards' onboard key rows (tag 0x110, onboard_keys.py), in G HUB's byte layout."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import onboard_keys as ok  # noqa: E402


class BaseLayerTest(unittest.TestCase):
	def test_parse_as_g_hub_writes(self):
		row = struct.pack('>BHHHH', 0, 0, 0x02, 0x8002, 0x04)
		mirror = struct.pack('>BHHHH', 1, 0x20, 0x02, 0x8002, 0x04)
		dpi = struct.pack('>BHHHH', 0, 0, 0, 0x9003, 0)
		data = bytes([2, 5, 2]) + row + mirror + bytes([9, 1]) + dpi
		self.assertEqual(ok.parse_base_layer(data), [(5, [(0, 0, 2, 0x8002, 4), (1, 0x20, 2, 0x8002, 4)]),
		                                              (9, [(0, 0, 0, 0x9003, 0)])])

	def test_rejects_what_isnt_exact(self):
		row = struct.pack('>BHHHH', 0, 0, 0, 0x9003, 0)
		self.assertIsNone(ok.parse_base_layer(bytes([1, 5, 1]) + row + b'\x00'))
		self.assertIsNone(ok.parse_base_layer(bytes([1, 5, 2]) + row))
		self.assertIsNone(ok.parse_base_layer(b''))
		self.assertIsNone(ok.parse_base_layer(None))

	def test_describe(self):
		self.assertEqual(ok.describe((0, 0, 0, 0x8002, 4), {4: 'A'}), 'A')
		self.assertEqual(ok.describe((0, 0, 0, 0x8001, 0b101)), 'mouse button 1, 3')
		self.assertEqual(ok.describe((0, 0, 0, 0x8003, 0xCD)), 'media 0xCD')
		self.assertEqual(ok.describe((0, 0, 0, 0x9008, 0)), 'next profile')
		self.assertEqual(ok.describe((0, 0, 0, 0x7000, 3)), 'action 0x7000 (3)')


class ProfileTagsTest(unittest.TestCase):
	def test_name_and_rate(self):
		import device_settings as ds
		self.assertEqual(ds.decode_profile_name('Gaming'.encode('utf-16-be').ljust(64, b'\0')), 'Gaming')
		self.assertEqual(ds.decode_profile_name(b'\xff' * 64), '')
		self.assertEqual((ds.decode_report_rate(b'\x03'), ds.decode_report_rate(b'\x00')), (1000, 125))
		self.assertIsNone(ds.decode_report_rate(b''))
		self.assertIsNone(ds.decode_report_rate(None))
		self.assertEqual(ds.decode_control_bitmap(bytes([0x81]) + bytes(14) + bytes([0x40])), [0, 7, 126])
		self.assertIsNone(ds.decode_control_bitmap(bytes(15)))


if __name__ == '__main__':
	unittest.main()


class ProfileSummaryTest(unittest.TestCase):
	def test_summary_from_tags(self):
		try:
			import hidpp_panel
		except (ImportError, ValueError):
			self.skipTest('GTK not available')
		from unittest import mock
		import device_settings as ds
		import features
		import mouse
		led = bytes([mouse.LED_FIXED, 1, 2, 3, 2]) + bytes(6)
		tags = {ds.PROFILE_NAME: 'P1'.encode('utf-16-be').ljust(64, b'\0'), ds.RATE_WIRED: b'\x03',
		        ds.GAME_MODE_KEYS: bytes([0b10]) + bytes(15), ds.IMMERSIVE_FLAG: b'\x01', 0x0104: led}
		with mock.patch.object(hidpp_panel, '_active_tag', side_effect=lambda _d, t: tags.get(t)), \
		     mock.patch.object(features, 'control_list', return_value=[0x10, 0x20]):
			p = hidpp_panel.read_profile_summary(None, {features.CONTROL_LIST})
		self.assertEqual((p['name'], p['wired'], p['game_mode']), ('P1', 1000, [0x20]))
		on, clusters = p['immersive']
		self.assertTrue(on)
		self.assertEqual([(k, c, l.color) for k, c, l in clusters], [('active', 0, (1, 2, 3))])
		self.assertNotIn('wireless', p)
