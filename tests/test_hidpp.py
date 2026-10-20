"""HID++ transport: requests, error answers, notifications, timeouts and finding the interface."""
import os
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hidpp  # noqa: E402

# A vendor collection with HID++ short and long reports (ids 0x10, 0x11)
VENDOR = bytes([0x06, 0x00, 0xFF, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x10, 0x75, 0x08, 0x95, 0x06, 0x81, 0x00,
                0x85, 0x11, 0x95, 0x13, 0x81, 0x00, 0xC0])
KEYBOARD = bytes([0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x01, 0xC0])


class Scripted:
	"""A transport that answers with prepared reports, one per read."""

	def __init__(self, replies):
		self.replies, self.written, self.lock = list(replies), [], threading.Lock()

	def write(self, data):
		self.written.append(bytes(data))

	def read(self, _timeout):
		return self.replies.pop(0) if self.replies else None

	def close(self):
		self.closed = True


def answer(index, func, params=b'', report=hidpp.LONG, device=hidpp.CORDED):
	return bytes([report, device, index, func << 4 | hidpp.SW_ID]) + params


class DeviceTest(unittest.TestCase):
	def test_answer_skips_other_reports_and_keeps_notifications(self):
		note = bytes([hidpp.LONG, hidpp.CORDED, 5, 0x10, 7])           # event 1 of feature index 5
		other = answer(3, 1, b'\x09', device=2)                          # another device's answer
		t = Scripted([b'', other, note, answer(3, 1, b'\x2a')])
		dev = hidpp.Device(t)
		self.assertEqual(dev.request(3, 1, b'\x01')[0], 0x2A)
		self.assertEqual(t.written[0][:5], bytes([hidpp.LONG, hidpp.CORDED, 3, 0x10 | hidpp.SW_ID, 1]))
		self.assertEqual(dev.next_event(0.1)[:2], (5, 1))                  # from the backlog
		self.assertIsNone(dev.next_event(0.01))

	def test_error_answers(self):
		error = bytes([hidpp.LONG, hidpp.CORDED, 0xFF, 3, 0x10 | hidpp.SW_ID, 8])
		dev = hidpp.Device(Scripted([answer(0, 0, b'\x03'), error]))
		with self.assertRaises(hidpp.HidppError) as e:
			dev.call(0x1234, 1)
		self.assertEqual(e.exception.code, 8)
		self.assertIn('busy', str(e.exception))
		self.assertIn('0x1234', str(e.exception))

	def test_missing_feature_and_no_reply(self):
		dev = hidpp.Device(Scripted([answer(0, 0, b'\x00')]))
		self.assertFalse(dev.has(0x8100))
		with self.assertRaises(hidpp.HidppError) as e:
			dev.call(0x8100, 0)
		self.assertEqual(e.exception.code, 6)
		silent = hidpp.Device(Scripted([]))
		with mock.patch.object(hidpp, 'TIMEOUT', 0.01), self.assertRaises(hidpp.NoReply):
			silent.request(1, 0)

	def test_report_size(self):
		dev = hidpp.Device(Scripted([]), reports=(hidpp.SHORT, hidpp.LONG, hidpp.VERY_LONG))
		self.assertEqual(dev._report_for(3), hidpp.SHORT)
		self.assertEqual(dev._report_for(10), hidpp.LONG)
		self.assertEqual(dev._report_for(30), hidpp.VERY_LONG)

	def test_what_every_device_answers(self):
		name = b'G502 X'
		replies = [answer(0, 1, b'\x04\x02'),                                               # protocol 4.2
		           answer(0, 0, b'\x01'), answer(1, 0, b'\x03'),                            # feature set: 3
		           answer(1, 1, b'\x00\x01'), answer(1, 1, b'\x00\x05'), answer(1, 1, b'\x00\x03'),
		           answer(2, 0, bytes([len(name)])), answer(2, 1, name),                    # name
		           answer(2, 2, b'\x03'),                                                    # kind: mouse
		           answer(3, 0, b'\x02'), answer(3, 1, b'\x01BOT'),                         # firmware entity 0: boot
		           answer(3, 1, b'\x00U1 \x12\x02' + struct.pack('>H', 7))]
		dev = hidpp.Device(Scripted(replies))
		self.assertEqual(dev.protocol_version(), (4, 2))
		self.assertEqual(dev.feature_list(), {hidpp.ROOT: 0, hidpp.FEATURE_SET: 1, hidpp.NAME: 2,
		                                      hidpp.FIRMWARE: 3})
		self.assertEqual(dev.name(), 'G502 X')
		self.assertEqual(dev.kind(), 'mouse')
		self.assertEqual(dev.firmware(), 'U1 12.02.B0007')

	def test_without_name_or_firmware(self):
		dev = hidpp.Device(Scripted([answer(0, 0, b'\x00')] * 4))
		self.assertEqual((dev.feature_list(), dev.name(), dev.kind(), dev.firmware()), ({hidpp.ROOT: 0}, '', '', ''))


class TransportTest(unittest.TestCase):
	def test_hidraw_transport_on_a_pipe(self):
		read_end, write_end = os.pipe()
		t = hidpp.HidrawTransport(f'/dev/fd/{read_end}')
		self.assertIsNone(t.read(0.01))
		os.write(write_end, b'\x11\xff\x00')
		self.assertEqual(t.read(0.5), b'\x11\xff\x00')
		t.close()
		t.close()                                     # twice is fine
		os.close(read_end)
		os.close(write_end)

	def test_finding_the_hidpp_interface(self):
		with tempfile.TemporaryDirectory() as root:
			for name, port, desc in (('hidraw1', '3-2', KEYBOARD), ('hidraw2', '3-2', VENDOR),
			                         ('hidraw3', '3-1', VENDOR)):
				dev = os.path.join(root, 'devices', port + ':1.2', name)
				os.makedirs(dev)
				with open(os.path.join(dev, 'report_descriptor'), 'wb') as f:
					f.write(desc)
				os.makedirs(os.path.join(root, 'class', name))
				os.symlink(dev, os.path.join(root, 'class', name, 'device'))
			with mock.patch.object(hidpp, 'SYS_HIDRAW', os.path.join(root, 'class')):
				found = hidpp.hidraw_for('3-2')
		self.assertEqual(found, [('/dev/hidraw2', {hidpp.SHORT, hidpp.LONG})])
		with mock.patch.object(hidpp, 'SYS_HIDRAW', '/nonexistent'):
			self.assertEqual(hidpp.hidraw_for('3-2'), [])

	def test_open_usb_tries_each_interface(self):
		silent = mock.Mock()
		silent.protocol_version.side_effect = hidpp.NoReply()
		good = mock.Mock()
		with mock.patch.object(hidpp, 'hidraw_for', return_value=[('/a', {0x11}), ('/b', {0x11}), ('/c', {0x11})]), \
				mock.patch.object(hidpp, 'HidrawTransport', side_effect=[OSError('busy'), 'tb', 'tc']), \
				mock.patch.object(hidpp, 'Device', side_effect=[silent, good]):
			self.assertIs(hidpp.open_usb('3-2'), good)
		silent.close.assert_called_once()
		with mock.patch.object(hidpp, 'hidraw_for', return_value=[]), self.assertRaises(OSError):
			hidpp.open_usb('3-2')

	def test_open_receiver(self):
		with mock.patch.object(hidpp, 'hidraw_for', return_value=[('/a', {0x10}), ('/b', {0x11})]), \
				mock.patch.object(hidpp, 'HidrawTransport', side_effect=[OSError('busy'), 'transport']):
			self.assertEqual(hidpp.open_receiver('3-2'), ('transport', {0x11}))
		with mock.patch.object(hidpp, 'hidraw_for', return_value=[]), self.assertRaises(OSError):
			hidpp.open_receiver('3-2')


if __name__ == '__main__':
	unittest.main()
