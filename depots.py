"""Product pictures, Blue VO!CE presets and the G HUB app icon, fetched from G HUB's update server the first time
a device shows up.

Each model's G HUB package (a "depot") holds its pictures. A depot can be tens of MB, but
it is just a header plus files laid end to end, and the server answers HTTP range requests,
so we read the header, hop over the file lengths, and download only the manifest and the
one picture it names for the model: a few hundred KB, once per model. Nothing from Logitech
is stored in this repo; the files land in ~/.local/share/lghub-bluevoice.
"""
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.request

import store

SERVER = 'https://updates.ghub.logitechg.com/depots/'
CORE_DEPOT = 'e4566bcc-25b0-4d8f-b4ad-170264654488/core.depot'   # G HUB's own files
MAGIC = 0x20170110
RETRY_AFTER = 7 * 24 * 3600     # after a failed fetch, wait a week before asking again
TIMEOUT = 20
MAX_BYTES = 8 << 20             # never download more than this for one picture

PRO_HEADSET = '6a0e41f1-e878-40e5-a68f-1b004dcccfa3/pro_headset.depot'   # PRO, PRO X, PRO X Wireless

# model -> depot path on the server (G HUB 2026.6). Keyboards ship one depot per layout; any
# layout has the same picture.
DEPOTS = {
	'4kpro': '8803c050-606c-4fe0-b031-b67f67d1a420/brio.depot',
	'brio': '8803c050-606c-4fe0-b031-b67f67d1a420/brio.depot',
	'c920': 'c687b3b1-1d0b-4579-885e-e18b9234a81c/c920.depot',
	'c922': '10eece5b-1b92-44ee-af7f-8760acf834b5/c922.depot',
	'g203': 'd1ddae43-a774-4e78-a814-075e4df42af7/g203.depot',
	'g203_lightsync': '585a75ef-1334-4c46-806c-ed00fd31ee61/g102_g203.depot',
	'g213': 'f74d234e-10d3-47e9-86f7-0a3ffa84f0d6/g213_us.depot',
	'g302': '1121b360-5d6d-4db1-aecc-1290b780762b/g302.depot',
	'g303': 'efaa814d-012a-4130-8599-5999c168e032/g303.depot',
	'g303_wireless': '1e65dc69-af01-4df2-9056-7b2c9fead644/g303_wireless.depot',
	'g305': 'c0a36ee6-2e72-4ef1-a0d0-eeb713f9ce5e/g305.depot',
	'g310': '338e4aa3-e107-408a-a7b7-df15cf6c1239/g310_us.depot',
	'g402': '5a2b53c5-fc45-4f72-8f63-175cc6c0be2e/g402.depot',
	'g403_hero': '9bf8cef7-6b2e-4f7d-b730-5749ae2c8a61/g403_hero.depot',
	'g403_wired': 'bfaada82-89bc-41c0-bfe1-4c3174dc7088/g403.depot',
	'g403_wireless': 'bfaada82-89bc-41c0-bfe1-4c3174dc7088/g403.depot',
	'g410': '45b73cc3-c7db-46b0-a63b-65b07ae74244/g410_us.depot',
	'g413': 'd3101c1f-4849-47ea-9eff-6682c4814208/g413_us.depot',
	'g430': '3ee0d8c5-a535-41a8-8af9-1f873a19dede/g430.depot',
	'g431': '92e3dd29-1751-42f9-a838-9a135fbd7c98/g431.depot',
	'g432': '79d0cd9a-7cdf-4e29-948d-295036d509f3/g432.depot',
	'g433': '43c6a56d-dcb6-43ea-ac32-6bb68ac2dbcd/g433.depot',
	'g502_core': 'abad2090-b231-447e-a009-92da906ed5d2/g502.depot',
	'g502_hero': '9807dc52-851c-4897-9ffc-118b43d46cd7/g502_hero.depot',
	'g502_spectrum': 'abad2090-b231-447e-a009-92da906ed5d2/g502.depot',
	'g502_wireless': 'c43c084c-778e-4fed-afff-1e7f534604e0/g502_wireless.depot',
	'g512_se': '9bfe3385-5d49-4efd-bbd5-34ba87e795aa/g512_se_us.depot',
	'g513': '4dd03491-4b45-4ee2-b9eb-6621bd002178/g513_us.depot',
	'g533': '4264db05-fd6e-45c2-bf3f-75cc1dbfb5ec/g533.depot',
	'g535': '695e8290-ee38-49ca-98c4-8b7403b9925c/g535.depot',
	'g560': 'b0069050-849c-4d84-8ce7-2660d1318c9e/g560.depot',
	'g600': '3cfd6816-c867-41fc-89cb-df30b7b4867e/g600.depot',
	'g602': 'aeebd958-68d4-4b40-990e-684e2e5eb8de/g602.depot',
	'g603': 'e358eb03-e706-46fd-bbfe-74f95585b09e/g603.depot',
	'g604': 'c7769c9e-1c16-4032-8d80-eded82b47c3a/g604.depot',
	'g610': '4a4fd269-35c7-479f-ad52-118ec013e09b/g610_us.depot',
	'g613': 'dcedaedd-0518-48c2-aa6f-d53f0a83c9ed/g613_us.depot',
	'g633': '8238ba79-9091-4f95-b25a-caeb71301281/g633.depot',
	'g635': '99562de2-7302-4aac-9b6e-bef959b673bf/g635.depot',
	'g703': 'e9027fb9-d321-4bb5-b093-57c5976224b1/g703.depot',
	'g703_hero': 'a2234eda-f301-4068-863a-78c624abb5fa/g703_hero.depot',
	'g733': '93bafee3-916e-4159-b036-d8b095e58785/g733_0ab5.depot',
	'g735': 'c8602496-866d-43d6-b78d-badd36479082/g735.depot',
	'g810': '97cd6a81-0edc-4a34-9851-84514a084e32/g810_us.depot',
	'g815': 'cba6bf94-e675-46b8-8cdb-767c974cb742/g815_us.depot',
	'g900': '7d98cfe0-fa95-4894-b3e0-5bd40ad34acf/g900.depot',
	'g903': '04fa103e-dea8-48f8-aba5-5aa683f71051/g903.depot',
	'g903_hero': '5447c557-795d-49ba-9e99-e8f646e4fc74/g903_hero.depot',
	'g910': '93bf0fa9-c234-4a5d-b001-1c6d3f797df3/g910_us.depot',
	'g915': '56c3de63-be63-4c3d-9a7b-cd62af2ede4b/g915_us.depot',
	'g915_tkl': '1259e86e-7ddf-4a6a-b160-5dc39742c20b/g915_tkl_us.depot',
	'g933': '84124ba0-6d3e-478e-a7e0-62d216bd517f/g933.depot',
	'g935': 'c968fa5f-8a51-4eef-80db-e3054d4d981b/g935.depot',
	'mx518': '6469527e-b76b-4a83-b5dc-84696d1691e8/mx518.depot',
	'powerplay': 'f1b572a3-03c1-4395-aaaa-ca17591417c6/powerplay.depot',
	'pro_71_gaming_headset': PRO_HEADSET,
	'pro_71_gaming_wireless_headset': PRO_HEADSET,
	'pro_gaming_headset': PRO_HEADSET,
	'pro_keyboard': 'e2a7e025-d300-4303-9978-e4b36e9bb934/pro_keyboard_us.depot',
	'pro_mouse': '2c37b174-47f6-4518-b97a-a31024d24ed3/pro_mouse.depot',
	'pro_mouse_hero': '5711e50d-69fe-4e4d-bbe5-fd21b963885b/pro_mouse_hero.depot',
	'pro_wireless_mouse': '5dee6af6-19ea-4804-afca-fe359ee12027/pro_wireless_mouse_depot.depot',
	'pro_x_wireless_mouse': 'd030e817-392a-4099-b03e-0ae67e94503c/pro_x_wireless_mouse.depot',
	'streamcam': '3b7cd140-3b80-415f-b75f-74eccbb196d6/streamcam.depot',
	'yeti_classic': '6b459da2-1753-4923-8064-a3c754e39a9e/yeti_classic.depot',
	'yeti_nano': '59d53c9f-5781-4110-8d6f-ce72b1af5ecd/yeti_nano.depot',
	'yeti_original_nano': 'ca866c59-0e96-4741-a0e3-0c7bec3918eb/yeti_original_nano.depot',
	'yeti_x': '3ad92e22-357d-4686-a935-a21ae1d9ed86/yetix.depot',
	'yeti_x_wow': '7b06e401-ae7e-471c-8042-b5930b9b5288/yetix_wow.depot',
}


def path_for(model):
	return os.path.join(store.IMAGE_DIR, f'{model}.png')


def _failed_marker(model):
	return os.path.join(store.IMAGE_DIR, f'.{model}.failed')


def _get(url, start, length):
	if length <= 0 or length > MAX_BYTES:
		raise ValueError(f'unexpected size {length}')
	req = urllib.request.Request(url, headers={'Range': f'bytes={start}-{start + length - 1}',
	                                           'User-Agent': 'Lghub'})
	with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed https server
		if r.status != 206:
			raise OSError('the server ignored the range request')
		data = r.read(length + 1)
	if len(data) != length:
		raise OSError('short read')
	return data


def _files(url):
	"""{name: (offset, size)} of a depot, from its header and the length before each file."""
	magic, header_len = struct.unpack('<II', _get(url, 0, 8))
	if magic != MAGIC:
		raise ValueError('not a G HUB depot')
	header = json.loads(_get(url, 8, header_len))
	files, pos = {}, 8 + header_len
	for entry in header['files']:
		size = struct.unpack('<I', _get(url, pos, 4))[0]
		pos += 4
		if size == 0xFFFFFFFF:        # large file: 64-bit length follows
			size = struct.unpack('<Q', _get(url, pos - 4, 8))[0]
			pos += 4
		files[entry['name']] = (pos, size)
		pos += size
	return files


def files_cached(url):
	"""_files(url), kept in the image folder after the first time: listing a large depot takes a
	request per file (over a minute for G HUB's core depot). The header's own bytes tell whether
	the depot changed."""
	import hashlib
	magic, header_len = struct.unpack('<II', _get(url, 0, 8))
	if magic != MAGIC:
		raise ValueError('not a G HUB depot')
	stamp = hashlib.sha256(_get(url, 8, header_len)).hexdigest()
	path = os.path.join(store.IMAGE_DIR, 'depot-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.json')
	try:
		with open(path) as f:
			cached = json.load(f)
		if cached.get('stamp') == stamp:
			return {k: tuple(v) for k, v in cached['files'].items()}
	except (OSError, ValueError, KeyError, AttributeError):
		pass
	files = _files(url)
	os.makedirs(store.IMAGE_DIR, exist_ok=True)
	with open(path + '.tmp', 'w') as f:
		json.dump({'stamp': stamp, 'files': files}, f)
	os.replace(path + '.tmp', path)
	return files


def _manifest_choice(model, manifest, files):
	for device in manifest.get('devices', []):
		if device.get('modelId') != model:
			continue
		for res in device.get('resources', []):
			if res.get('key') == 'device_image' and res.get('src') in files:
				return res['src']
	return None


def _pick(model, files, url):
	"""The picture the depot's manifest names for this model, else the first front view."""
	if 'manifest.json' in files:
		chosen = _manifest_choice(model, json.loads(_get(url, *files['manifest.json'])), files)
		if chosen:
			return chosen
	pictures = [n for n in files if n.lower().endswith(('.png', '.webp'))]
	return next((n for n in pictures if 'front' in n.lower()), pictures[0] if pictures else None)


def _to_png(data, out):
	"""Save PNG as is; convert WebP with whatever converter is installed."""
	if data[:8] == b'\x89PNG\r\n\x1a\n':
		with open(out, 'wb') as f:
			f.write(data)
		return True
	if data[:4] != b'RIFF' or data[8:12] != b'WEBP':
		return False
	with tempfile.TemporaryDirectory() as tmp:
		src = os.path.join(tmp, 'in.webp')
		dst = os.path.join(tmp, 'out.png')
		with open(src, 'wb') as f:
			f.write(data)
		for cmd in (['dwebp', src, '-o', dst], ['magick', src, dst], ['ffmpeg', '-loglevel', 'error', '-i', src, dst]):
			if shutil.which(cmd[0]) and subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0 \
					and os.path.exists(dst):
				shutil.move(dst, out)
				return True
	return False


def fetch_picture(model):
	"""Path of the model's picture, downloading it if needed; None if there is none (yet).
	Blocks on the network: call from a worker thread."""
	path = path_for(model)
	if os.path.exists(path):
		return path
	marker = _failed_marker(model)
	if model not in DEPOTS or (os.path.exists(marker) and time.time() - os.path.getmtime(marker) < RETRY_AFTER):
		return None
	os.makedirs(store.IMAGE_DIR, exist_ok=True)
	url = SERVER + DEPOTS[model]
	try:
		files = _files(url)
		name = _pick(model, files, url)
		if name and _to_png(_get(url, *files[name]), path + '.tmp'):
			os.replace(path + '.tmp', path)
			return path
	except (OSError, ValueError, KeyError, struct.error, subprocess.SubprocessError) as e:
		print(f'lghub: no picture for {model}: {e}', flush=True)
	with open(marker, 'w'):
		pass   # remember the failure (its mtime) so we don't ask the server again soon
	return None


def metadata_path(model):
	return os.path.join(store.IMAGE_DIR, f'{model}.metadata.json')


def fetch_metadata(model):
	"""Path of the model's metadata.json (G HUB's picture layout: key and button positions on the
	product picture, lighting zones), downloading it if needed; None if there is none. Blocks."""
	path = metadata_path(model)
	if os.path.exists(path):
		return path
	if model not in DEPOTS:
		return None
	url = SERVER + DEPOTS[model]
	try:
		files = _files(url)
		name = next((n for n in files if n.split('/')[-1].lower().startswith('metadata') and n.endswith('.json')), None)
		if not name:
			return None
		data = _get(url, *files[name])
		json.loads(data)
	except (OSError, ValueError, KeyError, struct.error) as e:
		print(f'lghub: no layout for {model}: {e}', flush=True)
		return None
	os.makedirs(store.IMAGE_DIR, exist_ok=True)
	with open(path + '.tmp', 'wb') as f:
		f.write(data)
	os.replace(path + '.tmp', path)
	return path


def battery_path(model):
	return os.path.join(store.IMAGE_DIR, f'{model}.battery.xml')


def fetch_battery(model, pid=None):
	"""Path of the model's battery.xml (G HUB's voltage curves for devices that report volts),
	downloading it if needed; None if there is none. Picks battery_<pid>.xml when there are
	several. Blocks."""
	path = battery_path(model)
	if os.path.exists(path):
		return path
	if model not in DEPOTS:
		return None
	url = SERVER + DEPOTS[model]
	try:
		files = _files(url)
		names = [n for n in files if n.split('/')[-1].lower().startswith('battery') and n.endswith('.xml')]
		name = next((n for n in names if pid and pid.lower() in n.lower()), names[0] if names else None)
		if not name:
			return None
		data = _get(url, *files[name])
	except (OSError, ValueError, KeyError, struct.error) as e:
		print(f'lghub: no battery curves for {model}: {e}', flush=True)
		return None
	os.makedirs(store.IMAGE_DIR, exist_ok=True)
	with open(path + '.tmp', 'wb') as f:
		f.write(data)
	os.replace(path + '.tmp', path)
	return path


# Headsets whose Blue VO!CE presets come from their depot at first sight (the G Pro X ones come
# with the installer): model -> (file in the depot, preset set in store.GHUB_PRESETS).
PRESET_FILES = {'g733': ('device_presets.json', 'g733')}


# G HUB's headset equalizer presets (LGHUB/data/eq_presets.json in the core depot): the file the
# headsets' LegacyEqualizer settings point into. Offset and hash pinned: one range request.
EQ_PRESETS_OFFSET = 314434397
EQ_PRESETS_SIZE = 4185
EQ_PRESETS_SHA256 = '4dfe1b79a0e62a5f9b1bba57cd2ce1a70d46652b2b476ef28240aaeceb67556c'


def fetch_eq_presets(path):
	"""G HUB's headset 10-band equalizer presets. True on success."""
	import hashlib
	try:
		data = _get(SERVER + CORE_DEPOT, EQ_PRESETS_OFFSET, EQ_PRESETS_SIZE)
	except (OSError, ValueError) as e:
		print(f'lghub: no equalizer presets: {e}', flush=True)
		return False
	if hashlib.sha256(data).hexdigest() != EQ_PRESETS_SHA256:
		print('lghub: the equalizer presets are not the expected file', flush=True)
		return False
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path + '.tmp', 'wb') as f:
		f.write(data)
	os.replace(path + '.tmp', path)
	return True


def fetch_presets(model):
	"""Path of the headset's G HUB preset file, downloading it if needed, or None. Blocks."""
	name, preset_set = PRESET_FILES[model]
	return _fetch_file(model, name, store.GHUB_PRESETS[preset_set])


def fetch_bv2_presets(model):
	"""Path of a Blue VO!CE 2 device's G HUB presets (its defaults_override.json), or None. Blocks."""
	import bv2_presets
	return _fetch_file(model, bv2_presets.DEPOT_FILE, bv2_presets.path_for(store.DATA_DIR, model))


def _fetch_file(model, name, path):
	if os.path.exists(path):
		return path
	url = SERVER + DEPOTS[model]
	try:
		files = _files(url)
		data = _get(url, *files[name])
		json.loads(data)
	except (OSError, ValueError, KeyError, struct.error) as e:
		print(f'lghub: no presets for {model}: {e}', flush=True)
		return None
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path + '.tmp', 'wb') as f:
		f.write(data)
	os.replace(path + '.tmp', path)
	return path


# --- the G HUB app icon ------------------------------------------------------------------------
# The 256 px icon in G HUB's software manager (core depot, G HUB 2026.6): the executable's place
# in the depot and the icon's hash are pinned, so this is six small range requests, checked.
ICON_EXE_OFFSET = 26003104
ICON_SHA256 = '743180184d0ebcc498f112c36845909496a1048793ba392294ef4660acfa9a08'
RT_ICON, RT_GROUP_ICON = 3, 14


class _Resources:
	"""A PE file's resource tree, read through read(offset, length)."""

	def __init__(self, read):
		self.read = read
		pe = struct.unpack('<I', read(0x3c, 4))[0]
		head = read(pe, 24 + 240)
		nsec, optsize = struct.unpack_from('<H', head, 6)[0], struct.unpack_from('<H', head, 20)[0]
		dirs = 24 + (112 if struct.unpack_from('<H', head, 24)[0] == 0x20b else 96)
		self.rva, size = struct.unpack_from('<II', head, dirs + 8 * 2)
		self.raw = self._section_offset(read(pe + 24 + optsize, 40 * nsec), nsec)
		self.data = read(self.raw, size)

	def _section_offset(self, secs, nsec):
		for i in range(nsec):
			vsz, va, rsz, raw = struct.unpack_from('<IIII', secs, 40 * i + 8)
			if va <= self.rva < va + max(vsz, rsz):
				return raw + self.rva - va
		raise ValueError('no resource section')

	def entries(self, off):
		named, ids = struct.unpack_from('<HH', self.data, off + 12)
		for k in range(named + ids):
			yield struct.unpack_from('<II', self.data, off + 16 + 8 * k)

	def leaf(self, ptr):
		while ptr >> 31:
			ptr = next(self.entries(ptr & 0x7fffffff))[1]
		rva, size = struct.unpack_from('<II', self.data, ptr)
		return self.read(self.raw + rva - self.rva, size)

	def of_type(self, kind):
		"""{id: entry pointer} for every resource of a type."""
		for typ, ptr in self.entries(0):
			if typ == kind:
				return dict(self.entries(ptr & 0x7fffffff))
		return {}


def _largest_icon(read):
	"""(width, image bytes) of the biggest image in a PE file's first icon group (the app's)."""
	res = _Resources(read)
	icons, groups = res.of_type(RT_ICON), list(res.of_type(RT_GROUP_ICON).values())
	if not groups:
		raise ValueError('no icon')
	group = res.leaf(groups[0])
	sizes = []
	for k in range(struct.unpack_from('<H', group, 4)[0]):
		width, *_rest, ident = struct.unpack_from('<BBBBHHIH', group, 6 + 14 * k)
		sizes.append((width or 256, ident))
	width, ident = max(sizes)
	return width, res.leaf(icons[ident])


def fetch_app_icon(out):
	"""Save G HUB's app icon as a 256 px PNG at out. True on success. Blocks on the network."""
	import hashlib

	import gi
	gi.require_version('GdkPixbuf', '2.0')
	from gi.repository import GdkPixbuf, GLib
	url = SERVER + CORE_DEPOT
	try:
		_width, image = _largest_icon(lambda offset, length: _get(url, ICON_EXE_OFFSET + offset, length))
	except (OSError, ValueError, KeyError, struct.error) as e:
		print(f'lghub: no G HUB icon: {e}', flush=True)
		return False
	if hashlib.sha256(image).hexdigest() != ICON_SHA256:
		print('lghub: the G HUB icon is not the expected one; keeping our own', flush=True)
		return False
	# Icon images are PNG or a bare bitmap; wrapped in a one-image .ico, GdkPixbuf reads both.
	ico = struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(image), 22) + image
	loader = GdkPixbuf.PixbufLoader.new_with_type('ico')
	try:
		loader.write(ico)
		loader.close()
		loader.get_pixbuf().savev(out, 'png', [], [])
	except GLib.Error as e:
		print(f'lghub: cannot convert the G HUB icon: {e}', flush=True)
		return False
	return True


if __name__ == '__main__':
	import sys
	if len(sys.argv) == 3 and sys.argv[1] == '--app-icon':
		sys.exit(0 if fetch_app_icon(sys.argv[2]) else 1)
	if len(sys.argv) == 3 and sys.argv[1] == '--eq-presets':
		sys.exit(0 if fetch_eq_presets(sys.argv[2]) else 1)
	sys.exit('usage: depots.py --app-icon OUT.png | --eq-presets OUT.json')
