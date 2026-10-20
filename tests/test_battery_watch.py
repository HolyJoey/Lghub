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

	def test_check_reads_devices_and_respects_the_setting(self):
		sent = []
		watch = battery_watch.Watch(send=lambda title, body: sent.append(title))
		dev = mock.Mock(id='r#1')
		dev.name = 'G733'
		with mock.patch.object(watch, '_readings', return_value=[(dev, (10, 'On battery'))]), \
				mock.patch('store.load_config', return_value={'battery_warnings': False}):
			watch.check(100.0)
		self.assertEqual((sent, watch.readings, watch.last), ([], {'r#1': ('G733', (10, 'On battery'))}, 100.0))
		self.assertTrue(watch.due(100.0 + battery_watch.CHECK_EVERY))
		with mock.patch.object(watch, '_readings', return_value=[(dev, (10, 'On battery'))]), \
				mock.patch('store.load_config', return_value={}):
			watch.check(200.0)
		self.assertEqual(sent, ['G733: battery critical'])

	def test_readings_walk_wireless_devices(self):
		model = mock.Mock(type='headset', flags={'battery'})
		corded = mock.Mock(model=mock.Mock(type='keyboard', flags=set()))
		receiver = mock.Mock(model=mock.Mock(type='receiver'))
		headset, behind = mock.Mock(model=model), mock.Mock(model=model)
		devices = mock.Mock()
		devices.discover.return_value = [headset, corded, receiver]
		devices.scan_receiver.return_value = [behind]
		hid = mock.Mock()
		hid.has.return_value = False
		devices.open_hidpp.side_effect = [hid, OSError('gone')]
		features = mock.Mock()
		features.battery.return_value = (50, 'On battery')
		with mock.patch.dict(sys.modules, {'devices': devices, 'features': features}):
			found = list(battery_watch.Watch()._readings())
		self.assertEqual(found, [(headset, (50, 'On battery'))])
		hid.close.assert_called_once()

	def test_notify_without_a_server(self):
		from gi.repository import GLib
		bus = mock.Mock()
		bus.call_sync.side_effect = GLib.Error('no server')
		with mock.patch('gi.repository.Gio.bus_get_sync', return_value=bus):
			self.assertEqual(battery_watch.notify('t', 'b'), 0)
		bus.call_sync.side_effect = None
		bus.call_sync.return_value = GLib.Variant('(u)', (42,))
		with mock.patch('gi.repository.Gio.bus_get_sync', return_value=bus):
			self.assertEqual(battery_watch.notify('t', 'b', replaces=3), 42)


if __name__ == '__main__':
	unittest.main()
