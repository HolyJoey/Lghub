"""The config store and the virtual input device (with /dev/uinput faked)."""
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import store  # noqa: E402
import uinput  # noqa: E402


class StoreTest(unittest.TestCase):
	def test_headset_model(self):
		self.assertEqual(store.headset_model({'headset': 'g733'}), 'g733')
		self.assertEqual(store.headset_model({}, hint='wireless'), 'wireless')
		self.assertEqual(store.headset_model({}, {'input': {'name': 'G733 Gaming Headset'}}), 'g733')
		self.assertEqual(store.headset_model({}, {'input': {'description': 'PRO X Wireless'}}), 'wireless')
		self.assertEqual(store.headset_model({}), 'wired')

	def test_user_presets_and_status(self):
		with tempfile.TemporaryDirectory() as d, mock.patch.object(store, 'PRESET_DIR', d), \
				mock.patch.object(store, 'STATUS_FILE', os.path.join(d, 'status.json')):
			store.save_user_preset('My / voice!', {'nr.enable': 1})
			self.assertEqual(store.list_user_presets(), ['My  voice'])
			self.assertEqual(store.load_user_preset('My / voice!')['nr.enable'], 1)
			self.assertIsNone(store.load_user_preset('missing'))
			store.delete_user_preset('My / voice!')
			store.delete_user_preset('My / voice!')          # already gone: fine
			self.assertEqual(store.list_user_presets(), [])
			store.write_status({'input': 'x'})
			self.assertEqual(store.read_status(), {'input': 'x'})
		self.assertEqual(store.safe_name('***'), 'preset')

	def test_config_keeps_defaults_for_missing_params(self):
		with tempfile.TemporaryDirectory() as d, mock.patch.object(store, 'CONFIG_FILE', os.path.join(d, 'c.json')):
			store.save_config({'enabled': False, 'params': {'nr.enable': 0}})
			cfg = store.load_config()
		self.assertFalse(cfg['enabled'])
		self.assertEqual(cfg['params']['nr.enable'], 0)
		self.assertGreater(len(cfg['params']), 1)


class UinputTest(unittest.TestCase):
	def test_events(self):
		written = []
		with mock.patch('os.open', return_value=99), mock.patch('fcntl.ioctl') as ioctl, \
				mock.patch('os.write', lambda fd, data: written.append(data)), mock.patch('time.sleep'), \
				mock.patch('os.close') as close:
			out = uinput.VirtualInput()
			self.assertTrue(out.usage(0x04, True))
			self.assertTrue(out.usage(0xe9, True, consumer=True))
			self.assertFalse(out.usage(0xFFFF, True))
			out.tap(uinput.BTN_LEFT)
			out.wheel(-1, horizontal=True)
			out.close()
		events = [struct.unpack('llHHi', w)[2:] for w in written]
		self.assertEqual(events[0], (uinput.EV_KEY, uinput.KEYBOARD[0x04], 1))
		self.assertEqual(events[1], (uinput.EV_SYN, uinput.SYN_REPORT, 0))
		self.assertEqual(events[2], (uinput.EV_KEY, uinput.CONSUMER[0xe9], 1))
		self.assertIn((uinput.EV_REL, uinput.REL_HWHEEL, -1), events)
		self.assertTrue(ioctl.called)
		close.assert_called_with(99)

	def test_no_access_closes(self):
		with mock.patch('os.open', return_value=5), mock.patch('fcntl.ioctl', side_effect=OSError('denied')), \
				mock.patch('os.close') as close:
			with self.assertRaises(OSError):
				uinput.VirtualInput()
		close.assert_called_with(5)


if __name__ == '__main__':
	unittest.main()
