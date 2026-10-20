"""The installer's download step: depots, DLLs found inside the driver installer, hash checks."""
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import fetch  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'pic'


def pe(pdb, signature=b''):
	"""A minimal 64-bit PE image: one section holding the PDB name, and an optional certificate
	(Authenticode signature) after it."""
	pe_off, opt_size = 0x40, 240
	head = bytearray(0x200)
	head[0:4] = b'MZ\x90\x00'
	struct.pack_into('<I', head, 0x3c, pe_off)
	head[pe_off:pe_off + 4] = b'PE\0\0'
	struct.pack_into('<HH', head, pe_off + 4, 0x8664, 1)                 # one section
	struct.pack_into('<H', head, pe_off + 20, opt_size)
	opt = pe_off + 24
	struct.pack_into('<H', head, opt, 0x20b)
	body = (pdb + '.pdb').encode().ljust(0x40, b'\0')
	section = opt + opt_size
	struct.pack_into('<II', head, section + 16, len(body), len(head))   # raw size, raw pointer
	if signature:
		struct.pack_into('<II', head, opt + 112 + 8 * 4, len(head) + len(body), len(signature))
	return bytes(head) + body + signature


def depot(files):
	header = json.dumps({'files': [{'name': n} for n, _d in files]}).encode()
	out = struct.pack('<II', fetch.DEPOT_MAGIC, len(header)) + header
	for _n, data in files:
		out += struct.pack('<I', len(data)) + data
	return out


class FetchTest(unittest.TestCase):
	def test_depot_files(self):
		self.assertEqual(fetch.depot_files(depot([('a', b'1'), ('b', b'22')])), {'a': b'1', 'b': b'22'})
		with self.assertRaises(ValueError):
			fetch.depot_files(b'\0' * 8)

	def test_embedded_pe_by_pdb_name(self):
		apo, surround = pe(fetch.APO_NAME, b'SIG'), pe(fetch.HX2E_NAME)
		exe = b'MZ\x90\x00 the installer itself ' + b'MZ\x90\x00junk' + bytes(64) + apo + surround
		self.assertEqual(fetch.embedded_pe(exe, fetch.APO_NAME), apo)               # signature kept
		self.assertEqual(fetch.embedded_pe(exe, fetch.HX2E_NAME), surround)
		with self.assertRaises(ValueError):
			fetch.embedded_pe(exe, 'missing')

	def test_save_images(self):
		manifest = json.dumps({'devices': [{'modelId': 'pro/x', 'resources': [{'key': 'device_image', 'src': 'i.png'}]},
		                                   {'modelId': 'g', 'resources': []}]}).encode()
		with tempfile.TemporaryDirectory() as d:
			fetch.save_images({'manifest.json': manifest, 'i.png': PNG}, d)
			self.assertEqual(os.listdir(d), ['prox.png'])
			fetch.save_images({}, os.path.join(d, 'none'))
			self.assertFalse(os.path.exists(os.path.join(d, 'none')))

	def test_main_installs_checked_files(self):
		exe = b'MZ\x90\x00' + pe(fetch.APO_NAME) + pe(fetch.HX2E_NAME) + pe(fetch.BV2_NAME)
		apo_depot = depot([(fetch.APO_EXE, exe)])
		headset = depot([('pro_x_headset_device_presets.json', b'{"p": 1}'), ('manifest.json', b'{}')])
		with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
			for name, data in (('driver_audio_apo', apo_depot), ('pro_headset', headset)):
				with open(os.path.join(src, name + '.depot'), 'wb') as f:
					f.write(data)
			hashes = {'driver_audio_apo': fetch.sha256(apo_depot), 'pro_headset': fetch.sha256(headset)}
			depots = {k: {**v, 'sha256': hashes[k]} for k, v in fetch.DEPOTS.items()}
			with mock.patch.object(fetch, 'DEPOTS', depots), \
					mock.patch.object(fetch, 'APO_SHA256', fetch.sha256(pe(fetch.APO_NAME))), \
					mock.patch.object(fetch, 'BV2_SHA256', fetch.sha256(pe(fetch.BV2_NAME))), \
					mock.patch.object(sys, 'argv', ['fetch.py', dest, '--depot-dir', src]), \
					mock.patch('builtins.print'):
				fetch.main()
			self.assertEqual(sorted(os.listdir(os.path.join(dest, 'apo'))),
			                 sorted([fetch.APO_NAME + '.dll', fetch.BV2_NAME + '.dll']))  # surround: wrong hash, off
			with open(os.path.join(dest, 'presets', 'pro_x_headset_device_presets.json')) as f:
				self.assertEqual(f.read(), '{"p": 1}')

	def test_wrong_depot_is_refused(self):
		with tempfile.TemporaryDirectory() as src:
			with open(os.path.join(src, 'pro_headset.depot'), 'wb') as f:
				f.write(b'not it')
			with self.assertRaises(SystemExit):
				fetch.get_depot('pro_headset', src)

	def test_download(self):
		r = mock.MagicMock()
		r.read.return_value = b'data'
		r.__enter__.return_value = r
		depots = {'pro_headset': {'url': 'https://x', 'sha256': fetch.sha256(b'data')}}
		with mock.patch.object(fetch, 'DEPOTS', depots), mock.patch('urllib.request.urlopen', return_value=r), \
				mock.patch('builtins.print'):
			self.assertEqual(fetch.get_depot('pro_headset', None), b'data')


if __name__ == '__main__':
	unittest.main()
