"""Finding devices: USB in sysfs, the simulator, models, and what's behind a receiver."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import devices  # noqa: E402
import hidpp  # noqa: E402


def usb_tree(root, entries):
	for name, vid, pid, serial in entries:
		base = os.path.join(root, name)
		os.makedirs(base)
		for f, value in (('idVendor', vid), ('idProduct', pid), ('serial', serial)):
			if value is not None:
				with open(os.path.join(base, f), 'w') as fh:
					fh.write(value + '\n')


class DiscoverTest(unittest.TestCase):
	def test_usb_devices_known_and_logitech_only(self):
		with tempfile.TemporaryDirectory() as root:
			usb_tree(root, [('3-2', '046d', 'C33F', 'ABC'), ('3-3', '046d', 'ffff', None),
			                ('3-4', '8087', '0026', None), ('3-2:1.0', '046d', 'c33f', None),
			                ('usb3', '1d6b', '0003', None), ('3-5', None, None, None)])
			with mock.patch.object(devices, 'SYS_USB', root), mock.patch.object(devices, 'SYS_HID', '/nonexistent'), \
					mock.patch.dict(os.environ, {devices.FAKE_ENV: ''}):
				found = devices.discover()
		self.assertEqual([(d.id, d.model.key, d.serial) for d in found],
		                 [('usb:3-2', 'g815', 'ABC'), ('usb:3-3', 'unknown', '')])
		g815 = found[0]
		self.assertEqual((g815.port, g815.wireless, g815.name), ('3-2', False, g815.model.name))
		self.assertTrue(g815.type_name)
		self.assertTrue(g815.icon)
		with mock.patch.object(devices, 'SYS_USB', '/nonexistent'):
			self.assertEqual(devices._usb_devices(), [])

	def test_bluetooth_devices(self):
		with tempfile.TemporaryDirectory() as root:
			for name, uevent in (('0005:046D:B354.0004', 'HID_NAME=G915\nHID_UNIQ=aa:bb\n'),
			                     ('0005:046D:B354.0005', 'HID_NAME=G915\nHID_UNIQ=aa:bb\n'),   # same device
			                     ('0005:046D:B0FF.0006', 'HID_NAME=Logitech G305\nHID_UNIQ=cc\n'),
			                     ('0005:046D:B0FE.0007', 'HID_UNIQ=dd\n'),
			                     ('0005:054C:0CE6.0008', 'HID_NAME=Wireless Controller\n'),
			                     ('0003:046D:C33F.0009', 'HID_NAME=G815\n')):
				os.makedirs(os.path.join(root, name))
				with open(os.path.join(root, name, 'uevent'), 'w') as f:
					f.write(uevent)
			with mock.patch.object(devices, 'SYS_USB', '/nonexistent'), mock.patch.object(devices, 'SYS_HID', root), \
					mock.patch.dict(os.environ, {devices.FAKE_ENV: ''}):
				found = devices.discover()
		self.assertEqual([(d.id, d.usb_id, d.model.key, d.serial) for d in found],
		                 [('bt:0005:046D:B0FE.0007', '046d:b0fe', 'unknown', 'dd'),
		                  ('bt:0005:046D:B0FF.0006', '046d:b0ff', 'g305', 'cc'),          # by its name
		                  ('bt:0005:046D:B354.0004', '046d:b354', 'g915', 'aa:bb')])      # Bluetooth id in the catalog
		g915 = found[2]
		self.assertEqual((g915.port, g915.bluetooth, g915.wireless, g915.link), ('0005:046D:B354.0004', True, False, 'Bluetooth'))
		self.assertEqual(found[0].name, 'Logitech device 046d:b0fe')
		self.assertEqual(devices.Device('usb:3-2', '046d:c33f', g915.model).link, 'USB')
		self.assertEqual(devices.Device('usb:3-2#1', '046d:c539', g915.model, index=1).link, 'wireless')
		with mock.patch.object(devices, 'SYS_HID', '/nonexistent'):
			self.assertEqual(devices._bluetooth_devices(), [])

	def test_models(self):
		self.assertEqual(devices.model_for('046d:c52b').type, 'receiver')
		self.assertEqual(devices.model_for('046d:1234').key, 'unknown')
		self.assertIsNone(devices.model_for('8087:0026'))
		self.assertEqual(devices.match_model('Something new', 'mouse').type, 'mouse')
		self.assertEqual(devices.blue_voice_model(mock.Mock(model=mock.Mock(key='pro_71_gaming_headset'))), 'wired')
		self.assertIsNone(devices.blue_voice_model(None))

	def test_fake_devices_and_receiver_scan(self):
		with mock.patch.dict(os.environ, {devices.FAKE_ENV: 'c33f, 046d:c539@r1'}), \
				mock.patch.object(devices, 'SYS_USB', '/nonexistent'), mock.patch.object(devices, 'SYS_HID', '/nonexistent'):
			found = devices.discover()
			self.assertEqual([d.id for d in found], ['usb:fake0', 'usb:r1'])
			keyboard = devices.open_hidpp(found[0])
			self.assertIsInstance(keyboard, hidpp.Device)
			paired = devices.scan_receiver(found[1])
		self.assertTrue(paired)
		self.assertTrue(all(p.wireless and p.id.startswith('usb:r1#') for p in paired))

	def test_no_simulated_device(self):
		with mock.patch.dict(os.environ, {devices.FAKE_ENV: '0aaa'}):
			headset = devices.Device('usb:fake0', '046d:0aaa', devices.model_for('046d:0aaa'))
			with self.assertRaises(OSError):
				devices.open_hidpp(headset)

	def test_real_devices_go_through_hidpp(self):
		d = devices.Device('usb:3-2', '046d:c33f', devices.model_for('046d:c33f'))
		with mock.patch.dict(os.environ, {devices.FAKE_ENV: ''}), \
				mock.patch.object(hidpp, 'open_usb', return_value='dev') as open_usb:
			self.assertEqual(devices.open_hidpp(d), 'dev')
		open_usb.assert_called_with('3-2', 0xFF)
		receiver = devices.Device('usb:3-1', '046d:c539', devices.model_for('046d:c539'))
		transport = mock.Mock()
		paired = [mock.Mock(index=2, kind='keyboard')]
		paired[0].name = 'G915 TKL LIGHTSPEED Wireless RGB Keyboard'
		with mock.patch.dict(os.environ, {devices.FAKE_ENV: ''}), \
				mock.patch.object(hidpp, 'open_receiver', return_value=(transport, {0x11})), \
				mock.patch('features.paired_devices', return_value=paired):
			found = devices.scan_receiver(receiver)
		self.assertEqual([(f.id, f.index) for f in found], [('usb:3-1#2', 2)])
		transport.close.assert_called_once()


if __name__ == '__main__':
	unittest.main()
