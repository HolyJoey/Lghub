"""Finding a device's HID interface in sysfs (centurion.find / open_usb, proeq.find), the PRO EQ card
against a fake chip, and fetching G HUB's signature catalog (depots.fetch_signature_colors)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import centurion  # noqa: E402
import depots  # noqa: E402
import hidpp  # noqa: E402
import proeq  # noqa: E402

# usage page 0xFFA0 usage 1, report id 0x51
CENTURION_DESC = bytes([0x06, 0xA0, 0xFF, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x51, 0xC0])
OTHER_DESC = bytes([0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0xC0])
# report 4 out, report 5 in (63 bytes each)
CHIP_DESC = bytes([0x06, 0x00, 0xFF, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x04, 0x75, 0x08, 0x95, 0x3F, 0x09, 0x01,
                   0x91, 0x02, 0x85, 0x05, 0x75, 0x08, 0x95, 0x3F, 0x09, 0x01, 0x81, 0x02, 0xC0])


def sysfs(root, descriptors):
	"""A fake /sys/class/hidraw: hidrawN/device/report_descriptor for each descriptor."""
	for i, desc in enumerate(descriptors):
		d = os.path.join(root, f'hidraw{i}', 'device')
		os.makedirs(d)
		if desc is not None:
			with open(os.path.join(d, 'report_descriptor'), 'wb') as f:
				f.write(desc)
	return root


class LookupTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		patch = mock.patch('hotplug.on_port', return_value=True)
		patch.start()
		self.addCleanup(patch.stop)

	def test_centurion_collection(self):
		pid = next(p for p, e in centurion.ENTRIES.items() if e[:2] == (0xFFA0, 1))
		root = sysfs(self.tmp.name, [OTHER_DESC, None, CENTURION_DESC])
		with mock.patch.object(centurion, 'SYS_HIDRAW', root):
			self.assertEqual(centurion.find('1-1', pid), ('/dev/hidraw2', 0x51))
			self.assertIsNone(centurion.find('1-1', 0x0001))
		with mock.patch.object(centurion, 'SYS_HIDRAW', os.path.join(root, 'missing')):
			self.assertIsNone(centurion.find('1-1', pid))
			with self.assertRaises(OSError):
				centurion.open_usb('1-1', pid)

	def test_centurion_device_that_does_not_answer(self):
		pid = next(iter(centurion.ENTRIES))

		class Dev:
			closed = False

			def __init__(self, *_a):
				pass

			def protocol_version(self):
				raise hidpp.HidppError(1)

			def close(self):
				Dev.closed = True
		with mock.patch.object(centurion, 'find', return_value=('/dev/x', 0x51)), \
		     mock.patch.object(centurion, 'CenturionTransport'), mock.patch.object(hidpp, 'Device', Dev):
			with self.assertRaises(OSError):
				centurion.open_usb('1-1', pid)
		self.assertTrue(Dev.closed)

	def test_centurion_transport_round_trip(self):
		pid = next(iter(centurion.ENTRIES))
		entry = centurion.ENTRIES[pid]
		sent = []

		class Raw:
			lock = None

			def __init__(self, _path):
				self.replies = []

			def write(self, data):
				sent.append(data)
				_page, _usage, prefix, length_byte, _packet = entry
				msg = centurion.unwrap(bytes(data), prefix, length_byte)
				for frag in centurion.fragments(msg, entry[4]):
					self.replies.append(centurion.wrap(frag, prefix, length_byte))

			def read(self, _timeout):
				return self.replies.pop(0) if self.replies else None

			def close(self):
				pass
		with mock.patch.object(hidpp, 'HidrawTransport', Raw):
			t = centurion.CenturionTransport('/dev/x', entry, 0x51)
			t.write(bytes([0x12, 0xFF, 5, 0x10, 1, 2, 3]))
			self.assertIsNotNone(t.read(0.5))
			self.assertIsNone(t.read(0.05))
			t.close()
		self.assertTrue(sent)

	def test_proeq_interface(self):
		root = sysfs(self.tmp.name, [OTHER_DESC, CHIP_DESC])
		with mock.patch.object(proeq, 'SYS_HIDRAW', root):
			self.assertEqual(proeq.find('3-2'), ('/dev/hidraw1', 64, 64))
		with mock.patch.object(proeq, 'SYS_HIDRAW', os.path.join(root, 'missing')):
			self.assertIsNone(proeq.find('3-2'))


class SignatureCatalogFetchTest(unittest.TestCase):
	def test_fetch_once(self):
		import store
		device_list = {'devices': [{'modelId': 'a20_x', 'capabilities': {'lightingSupport': {'zones': [
			{'supportedEffects': [{'id': 'SIGNATURE_ALGORITHMIC_ACTIVE', 'signature': True, 'name': 'ASTRO_POINT',
			                       'signatureSupport': {'signatureColorOne': {'hex': '#FC0000'}}}]}]}}}]}
		files = {'data/devices/devices_0001.json': 1, 'data/devices/devices_0002.json': 2, 'other': 3}

		def read(_url, n):
			if n == 2:
				raise OSError('not published')
			return json.dumps(device_list).encode()
		with tempfile.TemporaryDirectory() as tmp, mock.patch.object(store, 'IMAGE_DIR', tmp), \
		     mock.patch.object(depots, 'files_cached', return_value=files), \
		     mock.patch.object(depots, '_read', side_effect=read), \
		     mock.patch.object(depots, '_unseal', side_effect=lambda d: d):
			open(os.path.join(tmp, depots.SIGNATURE_COLORS_OLD), 'w').close()
			path = depots.fetch_signature_colors()
			with open(path) as f:
				out = json.load(f)
			self.assertEqual(out['a20_x']['_ids'], {'SIGNATURE_ALGORITHMIC_ACTIVE': 'astro_point'})
			self.assertFalse(os.path.exists(os.path.join(tmp, depots.SIGNATURE_COLORS_OLD)))
			self.assertEqual(depots.fetch_signature_colors(), path)

	def test_fetch_failure(self):
		import store
		with tempfile.TemporaryDirectory() as tmp, mock.patch.object(store, 'IMAGE_DIR', tmp), \
		     mock.patch.object(depots, 'files_cached', side_effect=OSError('offline')):
			self.assertIsNone(depots.fetch_signature_colors())


if __name__ == '__main__':
	unittest.main()
