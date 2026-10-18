#!/usr/bin/env python3
"""Fetch Logitech's Blue VO!CE files from G HUB's update server (they are not in this repo).

  driver_audio_apo depot -> ghub_audio_driver_apo.exe -> logi_audio_dts_studio_capture_apo.dll
  pro_headset depot      -> pro_x_headset_device_presets.json (the 22 G Pro X presets)

Depots are G HUB's package format: u32 magic 0x20170110, u32 header length, a JSON header
listing the files, then each file as a u32 length plus its bytes. The APO DLL is stored
uncompressed inside the driver installer; it is found by the PDB name in its debug data.

Usage: fetch.py DEST_DIR [--depot-dir DIR]   (DIR: use local .depot files instead of downloading)
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
import urllib.request

DEPOTS = {
	'driver_audio_apo': {
		'url': 'https://updates.ghub.logitechg.com/depots/95ac1553-7dcf-412f-b558-c1e610929c55/driver_audio_apo.depot',
		'sha256': '7998b516ee2231d59867a8ae65b4895b7ac06b89ff3492ba20259ac022e97392',
	},
	'pro_headset': {
		'url': 'https://updates.ghub.logitechg.com/depots/6a0e41f1-e878-40e5-a68f-1b004dcccfa3/pro_headset.depot',
		'sha256': '086e6b1aa913e1f85f5ccee3a497d6bebf79031d9bb0225bb667592bbc534cf0',
	},
}
APO_NAME = 'logi_audio_dts_studio_capture_apo'
APO_SHA256 = 'efaabe5c8b5a246ad5fb0d84a157c8a8330d055d601f041e43423cb0e53481a6'
DEPOT_MAGIC = 0x20170110


def sha256(data):
	return hashlib.sha256(data).hexdigest()


def get_depot(name, depot_dir):
	info = DEPOTS[name]
	if depot_dir:
		with open(os.path.join(depot_dir, name + '.depot'), 'rb') as f:
			data = f.read()
	else:
		print(f'Downloading {name}…', flush=True)
		with urllib.request.urlopen(info['url'], timeout=60) as r:
			data = r.read()
	if sha256(data) != info['sha256']:
		raise SystemExit(f'{name}.depot does not match the expected SHA-256; refusing to use it.\n'
		                 'Logitech may have published a newer version: see README, "Updating the depots".')
	return data


def depot_files(data):
	"""{file name: bytes} from a G HUB depot."""
	magic, header_len = struct.unpack_from('<II', data, 0)
	if magic != DEPOT_MAGIC:
		raise ValueError('not a G HUB depot')
	header = json.loads(data[8:8 + header_len])
	files, pos = {}, 8 + header_len
	for entry in header['files']:
		size = struct.unpack_from('<I', data, pos)[0]
		pos += 4
		files[entry['name']] = data[pos:pos + size]
		pos += size
	return files


def embedded_pe(data, pdb_name):
	"""The PE image inside `data` whose debug info names `pdb_name`.pdb."""
	for m in re.finditer(rb'MZ\x90\x00', data):
		start = m.start()
		if start == 0:
			continue
		pe = start + struct.unpack_from('<I', data, start + 0x3c)[0]
		if data[pe:pe + 4] != b'PE\0\0':
			continue
		sections = struct.unpack_from('<H', data, pe + 6)[0]
		opt = pe + 24
		table = opt + struct.unpack_from('<H', data, pe + 20)[0]
		end = max(sum(struct.unpack_from('<II', data, table + 40 * i + 16)) for i in range(sections))
		dirs = opt + (112 if struct.unpack_from('<H', data, opt)[0] == 0x20b else 96)
		cert_off, cert_size = struct.unpack_from('<II', data, dirs + 8 * 4)
		if cert_size and cert_off >= end:
			end = cert_off + cert_size  # keep the Authenticode signature
		image = data[start:start + end]
		if (pdb_name + '.pdb').encode() in image:
			return image
	raise ValueError(f'{pdb_name} not found')


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('dest')
	ap.add_argument('--depot-dir')
	args = ap.parse_args()

	apo_files = depot_files(get_depot('driver_audio_apo', args.depot_dir))
	dll = embedded_pe(apo_files['ghub_audio_driver_apo.exe'], APO_NAME)
	if sha256(dll) != APO_SHA256:
		raise SystemExit('The extracted Blue VO!CE DLL is not the expected build; refusing to install it.')
	os.makedirs(os.path.join(args.dest, 'apo'), exist_ok=True)
	with open(os.path.join(args.dest, 'apo', APO_NAME + '.dll'), 'wb') as f:
		f.write(dll)

	headset_files = depot_files(get_depot('pro_headset', args.depot_dir))
	os.makedirs(os.path.join(args.dest, 'presets'), exist_ok=True)
	for name in ('pro_x_headset_device_presets.json', 'pro_x_wireless_headset_device_presets.json'):
		if name in headset_files:
			with open(os.path.join(args.dest, 'presets', name), 'wb') as f:
				f.write(headset_files[name])
	print('Logitech files ready.')


if __name__ == '__main__':
	sys.exit(main())
