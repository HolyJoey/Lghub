"""Picking a model's files out of a depot with range reads (an in-memory depot, no network)."""
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import depots  # noqa: E402
import store  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'picture'


def depot(files):
	header = json.dumps({'files': [{'name': n, 'mode': 33206} for n, _ in files]}).encode()
	out = struct.pack('<II', depots.MAGIC, len(header)) + header
	for _name, data in files:
		out += struct.pack('<I', len(data)) + data
	return out


class ImagesTest(unittest.TestCase):
	def setUp(self):
		manifest = json.dumps({'devices': [{'modelId': 'g502_hero', 'resources': [
			{'key': 'device_image', 'src': 'images/device/front_hero.png'}]}]}).encode()
		self.data = depot([('images/device/front_lol.png', b'x' * 50), ('images/device/front_hero.png', PNG),
		                   ('manifest.json', manifest)])
		self.reads = 0

		def fake_get(_url, start, length):
			self.reads += 1
			return self.data[start:start + length]
		self.real_get = depots._get
		depots._get = fake_get
		self.tmp = tempfile.TemporaryDirectory()
		self.real_dir = store.IMAGE_DIR
		store.IMAGE_DIR = self.tmp.name

	def tearDown(self):
		depots._get = self.real_get
		store.IMAGE_DIR = self.real_dir
		self.tmp.cleanup()

	def test_manifest_picks_the_model_picture(self):
		path = depots.fetch_picture('g502_hero')
		with open(path, 'rb') as f:
			self.assertEqual(f.read(), PNG)
		self.assertLess(self.reads, 10)

	def test_failure_is_remembered(self):
		self.data = b'not a depot at all'
		self.assertIsNone(depots.fetch_picture('g502_hero'))
		self.data = b''
		self.assertIsNone(depots.fetch_picture('g502_hero'))   # not asked again within a week
		self.assertEqual(self.reads, 1)

	def test_presets(self):
		self.data = depot([('front.png', PNG), ('device_presets.json', b'{"presets": []}')])
		real = store.GHUB_PRESETS['g733']
		store.GHUB_PRESETS['g733'] = os.path.join(self.tmp.name, 'g733.json')
		try:
			path = depots.fetch_presets('g733')
			with open(path) as f:
				self.assertEqual(f.read(), '{"presets": []}')
		finally:
			store.GHUB_PRESETS['g733'] = real

	def test_unknown_model(self):
		self.assertIsNone(depots.fetch_picture('no_such_model'))
		self.assertEqual(self.reads, 0)

	def test_metadata_and_battery(self):
		self.data = depot([('front.png', PNG), ('data/metadata.json', b'{"images": []}'),
		                   ('battery_0ab5.xml', b'<a/>'), ('battery_0afe.xml', b'<b/>')])
		with open(depots.fetch_metadata('g733')) as f:
			self.assertEqual(f.read(), '{"images": []}')
		with open(depots.fetch_battery('g733', '0AFE')) as f:
			self.assertEqual(f.read(), '<b/>')
		reads = self.reads
		self.assertTrue(depots.fetch_battery('g733'))                       # cached on disk now
		self.assertEqual(self.reads, reads)
		self.assertIsNone(depots.fetch_metadata('no_such_model'))
		self.assertIsNone(depots.fetch_battery('no_such_model'))

	def test_missing_files(self):
		self.data = depot([('front.png', PNG)])
		self.assertIsNone(depots.fetch_metadata('g733'))
		self.assertIsNone(depots.fetch_battery('g733'))
		self.data = b'junk'
		self.assertIsNone(depots.fetch_metadata('g502_hero'))
		self.assertIsNone(depots.fetch_battery('g502_hero'))

	def test_listing_is_cached_until_the_header_changes(self):
		self.data = depot([('a.json', b'{}'), ('b.json', b'[]')])
		files = depots.files_cached('https://x/d.depot')
		self.assertEqual(files['b.json'][1], 2)
		reads = self.reads
		self.assertEqual(depots.files_cached('https://x/d.depot'), files)
		self.assertEqual(self.reads - reads, 2)                             # just the header, again
		self.data = depot([('c.json', b'{}')])
		self.assertIn('c.json', depots.files_cached('https://x/d.depot'))
		self.data = b'junk1234'
		with self.assertRaises(ValueError):
			depots.files_cached('https://x/d.depot')

	def test_large_file_length(self):
		header = json.dumps({'files': [{'name': 'big.bin'}]}).encode()
		self.data = struct.pack('<II', depots.MAGIC, len(header)) + header + struct.pack('<IQ', 0xFFFFFFFF, 3) + b'abc'
		offset, size = depots._files('u')['big.bin']
		self.assertEqual((size, self.data[offset:offset + size]), (3, b'abc'))

	def test_eq_presets_are_checked(self):
		import hashlib
		body = b'{"presets": 1}'
		out = os.path.join(self.tmp.name, 'eq', 'presets.json')
		with mock.patch.object(depots, '_get', return_value=body):
			self.assertFalse(depots.fetch_eq_presets(out))                 # not the pinned file
			with mock.patch.object(depots, 'EQ_PRESETS_SHA256', hashlib.sha256(body).hexdigest()):
				self.assertTrue(depots.fetch_eq_presets(out))
		with mock.patch.object(depots, '_get', side_effect=OSError('offline')):
			self.assertFalse(depots.fetch_eq_presets(out))
		with open(out, 'rb') as f:
			self.assertEqual(f.read(), body)

	def test_bv2_presets(self):
		import bv2_presets
		self.data = depot([(bv2_presets.DEPOT_FILE, b'{"x": 1}')])
		with mock.patch.object(store, 'DATA_DIR', self.tmp.name):
			path = depots.fetch_bv2_presets('yeti_x')
		with open(path) as f:
			self.assertEqual(f.read(), '{"x": 1}')

	def test_pictures_that_are_neither_png_nor_webp(self):
		out = os.path.join(self.tmp.name, 'x.png')
		self.assertFalse(depots._to_png(b'GIF89a', out))
		with mock.patch('shutil.which', return_value=None):
			self.assertFalse(depots._to_png(b'RIFF\0\0\0\0WEBPVP8 ', out))


class RangeRequestTest(unittest.TestCase):
	def response(self, status, body):
		r = mock.MagicMock(status=status)
		r.read.return_value = body
		r.__enter__.return_value = r
		return r

	def test_get(self):
		with mock.patch('urllib.request.urlopen', return_value=self.response(206, b'abcd')) as urlopen:
			self.assertEqual(depots._get('https://x', 10, 4), b'abcd')
		self.assertEqual(urlopen.call_args.args[0].headers['Range'], 'bytes=10-13')
		with mock.patch('urllib.request.urlopen', return_value=self.response(200, b'abcd')), \
				self.assertRaises(OSError):
			depots._get('https://x', 0, 4)
		with mock.patch('urllib.request.urlopen', return_value=self.response(206, b'ab')), \
				self.assertRaises(OSError):
			depots._get('https://x', 0, 4)
		with self.assertRaises(ValueError):
			depots._get('https://x', 0, depots.MAX_BYTES + 1)


if __name__ == '__main__':
	unittest.main()
