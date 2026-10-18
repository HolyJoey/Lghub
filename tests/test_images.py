"""Picking a model's picture out of a depot with range reads (an in-memory depot, no network)."""
import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import images  # noqa: E402
import store  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'picture'


def depot(files):
	header = json.dumps({'files': [{'name': n, 'mode': 33206} for n, _ in files]}).encode()
	out = struct.pack('<II', images.MAGIC, len(header)) + header
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
		self.real_get = images._get
		images._get = fake_get
		self.tmp = tempfile.TemporaryDirectory()
		self.real_dir = store.IMAGE_DIR
		store.IMAGE_DIR = self.tmp.name

	def tearDown(self):
		images._get = self.real_get
		store.IMAGE_DIR = self.real_dir
		self.tmp.cleanup()

	def test_manifest_picks_the_model_picture(self):
		path = images.fetch('g502_hero')
		with open(path, 'rb') as f:
			self.assertEqual(f.read(), PNG)
		self.assertLess(self.reads, 10)

	def test_failure_is_remembered(self):
		self.data = b'not a depot at all'
		self.assertIsNone(images.fetch('g502_hero'))
		self.data = b''
		self.assertIsNone(images.fetch('g502_hero'))   # not asked again within a week
		self.assertEqual(self.reads, 1)

	def test_unknown_model(self):
		self.assertIsNone(images.fetch('no_such_model'))
		self.assertEqual(self.reads, 0)


if __name__ == '__main__':
	unittest.main()
