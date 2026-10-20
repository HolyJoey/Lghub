"""Saved settings go back on when a device appears."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import features  # noqa: E402
import hidpp  # noqa: E402
import perkey  # noqa: E402
import restore  # noqa: E402
import simulate  # noqa: E402
import store  # noqa: E402


class RestoreTest(unittest.TestCase):
	def test_apply_saved(self):
		with tempfile.TemporaryDirectory() as d, mock.patch.object(store, 'CONFIG_DIR', d):
			self.assertFalse(restore.anything_saved())
			perkey.save_colors('g815', {'PERKEY_KEYBOARD:4': [255, 0, 0]})
			features.save_game_mode_keys('g815', [0xE3])
			self.assertTrue(restore.anything_saved())
			kb = simulate.FakeKeyboard()
			restore.apply_saved(hidpp.Device(kb), 'g815')
			self.assertEqual(kb.keys[1], (255, 0, 0))
			self.assertEqual(kb.disabled, {0xE3})

	def test_check_restores_new_devices_once(self):
		kb = mock.Mock(id='usb:kb', model=mock.Mock(type='keyboard', key='g815'))
		kb.name = 'G815'
		receiver = mock.Mock(id='usb:rx', model=mock.Mock(type='receiver'))
		behind = mock.Mock(id='rx#1', model=mock.Mock(type='mouse', key='g502'))
		behind.name = 'G502'
		devices = mock.Mock()
		devices.discover.return_value = [kb, receiver]
		devices.scan_receiver.return_value = [behind]
		busy = [behind]                                                         # the G502 is busy the first time

		def open_hidpp(d):
			if d in busy:
				busy.remove(d)
				raise OSError('busy')
			return mock.Mock()

		devices.open_hidpp.side_effect = open_hidpp
		with mock.patch('hotplug.Watch'), mock.patch('receiver_watch.Watch'):
			r = restore.Restorer()
		saved = {'g815': ({'k': [1, 2, 3]}, []), 'g502': ({}, [4])}
		with mock.patch.dict(sys.modules, {'devices': devices}), \
				mock.patch.object(restore, 'anything_saved', return_value=True), \
				mock.patch.object(restore, 'saved_for', lambda key: saved.get(key, ({}, []))), \
				mock.patch.object(restore, 'apply_saved') as apply_:
			r.check(1.0)
			self.assertEqual([c.args[1] for c in apply_.call_args_list], ['g815'])    # the G502 was busy
			self.assertEqual(r.present, {'usb:kb', 'rx#1'})
			r.check(2.0)
			self.assertEqual(len(apply_.call_args_list), 1)                          # already there
			r.present.discard('rx#1')                                              # it went away and came back
			r.check(3.0)
		self.assertEqual([c.args[1] for c in apply_.call_args_list], ['g815', 'g502'])
		r.wireless.follow.assert_called_with([receiver])

	def test_check_does_nothing_without_saved_settings(self):
		with mock.patch('hotplug.Watch'), mock.patch('receiver_watch.Watch'):
			r = restore.Restorer()
		r.present = {'x'}
		with mock.patch.object(restore, 'anything_saved', return_value=False):
			r.check(1.0)
		self.assertEqual(r.present, set())
		r.hid.changed.return_value = False
		r.wireless.changed.return_value = False
		self.assertTrue(r.due(1.0 + restore.CHECK_EVERY))


if __name__ == '__main__':
	unittest.main()
