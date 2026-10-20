"""Product pictures, Blue VO!CE presets and the G HUB app icon, fetched from G HUB's update server the first time
a device shows up.

Each model's G HUB package (a "depot") holds its pictures. A depot can be tens of MB, but
it is just a header plus files laid end to end, and the server answers HTTP range requests,
so we read the header, hop over the file lengths, and download only the manifest and the
one picture it names for the model: a few hundred KB, once per model. Nothing from Logitech
is stored in this repo; the files land in ~/.local/share/lghub-bluevoice.

Newer depots are G HUB "capsules": the same layout, but the file list and each file are
encrypted (AES-128-GCM). The keys are the ones G HUB itself downloads from the same server
(its public update channel); they are fetched when first needed and kept with the pictures.
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
CAPSULE = 0x20210506           # encrypted depot
SEALED = 0x20210521            # an encrypted single file (also inside capsules)
PIPELINE = 'https://updates.ghub.logitechg.com/pipeline/v2/'
CHANNEL = 'update/ghub13/win/public/'   # G HUB's own app id and public channel (its pipeline.json)
KEYS_FILE = 'ghub-keys.json'
RETRY_AFTER = 7 * 24 * 3600     # after a failed fetch, wait a week before asking again
TIMEOUT = 20
MAX_BYTES = 8 << 20             # never download more than this for one picture

PRO_HEADSET = '6a0e41f1-e878-40e5-a68f-1b004dcccfa3/pro_headset.depot'   # PRO, PRO X, PRO X Wireless

# model -> depot path on the server (G HUB 2026.6, its details.json). Keyboards ship one depot per
# layout; any layout has the same picture (US taken).
DEPOTS = {
	'4kpro': '8803c050-606c-4fe0-b031-b67f67d1a420/brio.depot',
	'a20_x': '390d0f8a-85b4-4fdf-b153-36a2502db749/1c835082-43ce-40f2-93ca-80b95279778a.depot',
	'a50': 'b534153b-539a-4671-9f1e-94a42a62a4c6/bf6f516d-b41d-4ae7-911f-b08e86c829e3.depot',
	'a50_x': '8d74d088-279c-4d8c-945f-abaf0b52b126/8074da8b-78a1-42ca-bfbe-a99c2f924231.depot',
	'brio': '8803c050-606c-4fe0-b031-b67f67d1a420/brio.depot',
	'brio_500': '87c22ae2-c565-4384-b35a-6a43075a54cd/85875e86-f3e1-4e79-91ee-232575e2807f.depot',
	'brio_501': '4e1bd809-10ec-4251-a63e-1713a5420555/809506ef-f10a-4226-b105-8424388e7ad5.depot',
	'brio_505': '962fa2f6-2233-4431-a37a-ad8f1d952b37/3f4405f7-ba51-4dfb-b073-2af81b0996ef.depot',
	'brio_700': '2f8666aa-ecf7-4451-9553-87c22519d37a/cf22b71e-6011-4db3-adb7-ca2e29e3a66c.depot',
	'brio_705': '6c900ca7-1d49-4028-ac5b-3d3e3df3d7dc/b33be2d7-9bb6-41a2-a474-3a55f1700f9d.depot',
	'c920': 'c687b3b1-1d0b-4579-885e-e18b9234a81c/c920.depot',
	'c922': '10eece5b-1b92-44ee-af7f-8760acf834b5/c922.depot',
	'c930n': 'd41c3177-fe03-4232-9097-e082881471af/3ae519c1-cd1f-4fac-a6ab-1c7d29f24ecc.depot',
	'c930s': '26ac43ac-5f65-4c5f-b1ab-6b44b2531ae1/4949cb5f-4cba-4919-acc6-cebc1e325df8.depot',
	'g203': 'd1ddae43-a774-4e78-a814-075e4df42af7/g203.depot',
	'g203_lightsync': '585a75ef-1334-4c46-806c-ed00fd31ee61/g102_g203.depot',
	'g213': 'f74d234e-10d3-47e9-86f7-0a3ffa84f0d6/g213_us.depot',
	'g302': '1121b360-5d6d-4db1-aecc-1290b780762b/g302.depot',
	'g303': 'efaa814d-012a-4130-8599-5999c168e032/g303.depot',
	'g303_wireless': '1e65dc69-af01-4df2-9056-7b2c9fead644/g303_wireless.depot',
	'g304x': '53fbc81f-1652-4828-b479-dfc8a7c1e9c1/e2a8e5b2-ae29-4a51-99dc-cc360bb970cf.depot',
	'g305': 'c0a36ee6-2e72-4ef1-a0d0-eeb713f9ce5e/g305.depot',
	'g305_x': 'a6fc5033-809c-4477-ab83-8616d66a925a/0d085330-7f9d-458b-b71e-9fb1f9e0bf43.depot',
	'g309': '6d4f8b01-d390-43a9-acb4-d339b022e645/3be0a036-daa1-4278-8026-de8b5270d1a9.depot',
	'g310': '338e4aa3-e107-408a-a7b7-df15cf6c1239/g310_us.depot',
	'g316': 'df52d708-d75d-4c04-b69d-14e299d7517c/ca3a7ac2-5171-4d12-842a-4172f9c1d26b.depot',
	'g316x': '8867de7b-c541-4f79-8c49-b1e808867304/2bec9a95-b8b6-4cc3-a5e6-82a466bb2d32.depot',
	'g316x_ww_75': 'aa7a8e41-eda2-4828-9f2c-a240967cb797/ea8c44dc-82bf-460d-b2eb-c6cfec19909d.depot',
	'g316x_ww_98': 'da9c1a26-26c6-435a-b8c3-aee479f689ff/35ff0dc2-4a1e-42be-89ab-bf064418945a.depot',
	'g325': 'd00c6d0e-8e5d-4ece-bd32-5a89aa25a258/fea2de54-d088-419f-88ee-06415eb17698.depot',
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
	'g502x': '224c178d-961c-4a3a-8372-d0569f6c60cc/c2faa1f8-29e1-4807-af39-ad470c43b872.depot',
	'g502x_lightspeed': '5b944dbc-e9cf-4a0d-a5c6-25b31073a6ae/a33e3279-a071-4e44-a540-69563ca5a0a8.depot',
	'g502x_plus': '8fb7c731-9aaf-4ccd-b4c0-f746e2c3a865/97b085d9-0fde-406b-8bcd-b244746387e7.depot',
	'g502x_wl': 'c3b46dd7-0d06-4de4-b0a8-b9da1fe8b164/4b69eab3-c305-42ce-a98c-03a7247d06b2.depot',
	'g512_se': '9bfe3385-5d49-4efd-bbd5-34ba87e795aa/g512_se_us.depot',
	'g512_x_75': '4b765412-c16d-4c30-861b-2974c6f0ff79/595a01d7-4f1e-4600-851e-2c6e71461b24.depot',
	'g512_x_98': '7c78c6cd-6485-4bb0-ac72-cdfa6331bc6a/b3e76c83-9667-42dd-875e-130d3f0583ce.depot',
	'g513': '4dd03491-4b45-4ee2-b9eb-6621bd002178/g513_us.depot',
	'g515_ls_tkl': 'b1a8c75f-b494-4c45-93c5-549214e1a8c6/976a554b-f096-4788-a9e1-301c8dcd8de3.depot',
	'g515_tkl': '753989a3-8ab0-4e6a-9cb5-91aaf44460e8/40415a1f-2565-449a-bfa5-9dd85205e253.depot',
	'g515_tkl_rapid': '5e1f501f-5887-4e37-b74c-12a3c9ba4ee9/8a47c541-db43-4641-b514-266288bdb93f.depot',
	'g517_ls_tkl': '2d640705-7124-4673-8877-75c7b6ce907f/09a9f2d2-e759-4f21-bec1-0c1ac618b3cb.depot',
	'g522': '39863ca9-773a-4ea2-b1d5-6d7c8319a8ec/ab60b41d-80d9-4a6c-b2be-65436b76070d.depot',
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
	'g705': '2ba420aa-6026-48e7-b873-fbed0487e337/c69d172e-a23c-421b-a5f0-d7f18c8d127c.depot',
	'g713': '2cf1951c-cbe7-44c6-aa44-f2ec8e9f44c7/070460a0-f4ac-419c-856e-bdee7b3fb66f.depot',
	'g715': 'f4f2fb22-45b7-4a47-b6db-c9416a2f351f/dca1192d-ace8-48d4-b4f0-4eafd7e81a90.depot',
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
	'g915_x': '5725afdb-141d-45b9-af27-bd9fe96a7d8f/8a4ebfbf-ca9c-434e-91e6-cd6a61a82397.depot',
	'g915_x_ls': '1e0be63c-3a29-42f3-982f-131230ce7b0c/0f9d5591-f106-4635-865f-dcfff3e2b781.depot',
	'g915_x_ls_tkl': '88568842-02fc-4202-895f-33af28effef3/fd06962e-6e72-4606-bacc-88d9425f31f3.depot',
	'g933': '84124ba0-6d3e-478e-a7e0-62d216bd517f/g933.depot',
	'g935': 'c968fa5f-8a51-4eef-80db-e3054d4d981b/g935.depot',
	'g_fits': '825bbf12-4981-4a18-9643-e01454fb9d98/65f9e7a5-2f4c-4ee3-8b5c-10d856baf847.depot',
	'litra_beam': 'a14719cc-7e4b-483f-9bc9-a8063d17b5cf/c3c4ac7f-10c5-425f-9872-968c2e35cf2e.depot',
	'litra_beam_lx': 'e246d2b0-bb76-4030-8d5a-8046c33b7fd1/dcc226e3-fa1b-40a3-9b26-c687ff62dd80.depot',
	'litra_glow': 'b32b88d2-41e8-4481-9ee4-199187471c43/95e074bb-3756-4e14-b7ed-f3ba899826b3.depot',
	'mx518': '6469527e-b76b-4a83-b5dc-84696d1691e8/mx518.depot',
	'powerplay': 'f1b572a3-03c1-4395-aaaa-ca17591417c6/powerplay.depot',
	'pro_2_wireless_mouse': '14b48e52-924d-41ed-b2e5-cb0e79114760/4641b15e-c030-4e6f-bd28-3d0d07ca0250.depot',
	'pro_71_gaming_headset': PRO_HEADSET,
	'pro_71_gaming_wireless_headset': PRO_HEADSET,
	'pro_gaming_headset': PRO_HEADSET,
	'pro_keyboard': 'e2a7e025-d300-4303-9978-e4b36e9bb934/pro_keyboard_us.depot',
	'pro_mouse': '2c37b174-47f6-4518-b97a-a31024d24ed3/pro_mouse.depot',
	'pro_mouse_hero': '5711e50d-69fe-4e4d-bbe5-fd21b963885b/pro_mouse_hero.depot',
	'pro_wireless_mouse': '5dee6af6-19ea-4804-afca-fe359ee12027/pro_wireless_mouse_depot.depot',
	'pro_x2_gaming_wireless_headset': 'e00aaada-032f-4417-a44d-da2184ffbf77/097fdd67-a78f-4e1f-8807-f2fc4f951705.depot',
	'pro_x2_rapid': 'f2663176-dd09-480d-a8fa-8b18e13af9f7/a921423a-c953-4f95-afa8-440e7339549d.depot',
	'pro_x3_gaming_wireless_headset': '314e4c98-1ac3-41ae-b5c5-528be4f52624/a6691c36-0981-43dd-b41a-a404866a9105.depot',
	'pro_x_1_superstrike_wireless_mouse': '6aff8c3f-d042-4990-bd1c-bc481eca922c/f09f1070-bfd5-4f9e-9dcf-91f15da2273b.depot',
	'pro_x_2_compact_wireless_mouse': '8990555d-bba3-4205-bbe4-5f9118ee7706/3fb3e67d-372d-4f50-8c78-8c82beccba09.depot',
	'pro_x_2_superstrike_wireless_mouse': 'abafa59b-050a-43ed-b745-e367059e359a/fe61de21-a6c5-46d0-8e2f-f71e37d6c766.depot',
	'pro_x_2_wireless_mouse': '643e9648-5304-4786-932a-b7759fcc39dc/a61bf574-f5f1-4bb6-b971-12e369cb0b92.depot',
	'pro_x_3_superstrike_wireless_mouse': '40f45e37-003c-47e2-a2f3-47b2e5a33b8f/d34391a4-e9ea-4ea7-b3bd-a157ca83562e.depot',
	'pro_x_60': 'b78c8772-495d-4fde-9932-f176a43b3dda/60fcc10b-59b2-4c8c-97dd-9fb3340842fa.depot',
	'pro_x_r_wireless_mouse': 'addb6dcb-9c2f-4a75-8fd3-38f88abbd825/7044b939-ba7b-440a-95ec-c65f8d6b9fb5.depot',
	'pro_x_tkl': 'a454bc0d-58bf-4258-a9c7-264ac8868c37/e58b079f-3ef0-4124-91e1-99366841bd83.depot',
	'pro_x_tkl_rapid': 'ee7d1d97-0dd1-4351-8bfb-6d5591b6eb05/449086f0-92c0-457c-8792-621fbac55f29.depot',
	'pro_x_wireless_mouse': 'd030e817-392a-4099-b03e-0ae67e94503c/pro_x_wireless_mouse.depot',
	'reach': '025840c8-f3de-40a7-a74f-8d290686171f/c77b8df5-8f33-45c1-9cbc-0db7a9d34b20.depot',
	'streamcam': '3b7cd140-3b80-415f-b75f-74eccbb196d6/streamcam.depot',
	'yeti_2': '82747b4a-4976-4628-89ad-a23e8f27c6ba/97dc0e52-037f-4c2f-ada2-5901cfe4552a.depot',
	'yeti_classic': '6b459da2-1753-4923-8064-a3c754e39a9e/yeti_classic.depot',
	'yeti_gx': '818c90db-bacf-476a-8737-45a93343333e/cba8a7c9-04e8-4c43-aaae-1af8ab629e01.depot',
	'yeti_nano': '59d53c9f-5781-4110-8d6f-ce72b1af5ecd/yeti_nano.depot',
	'yeti_orb': '6986cb5f-ede5-418f-a722-d645becee7a2/818e325e-9d21-4f8d-be79-9aae233776d6.depot',
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


def _fetch_json(url):
	req = urllib.request.Request(url, headers={'User-Agent': 'Lghub'})
	with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed https server
		return json.loads(r.read(4 << 20))


def _keys(key_id):
	"""The capsule key (16 bytes) named key_id: from the cached key list, else fetched again the way
	G HUB gets it (the channel's details name an access group, whose content lists the keys)."""
	import base64
	path = os.path.join(store.IMAGE_DIR, KEYS_FILE)
	for fresh in (False, True):
		if fresh:
			group = _fetch_json(PIPELINE + CHANNEL + 'details.json')['keys']['accessGroup']
			content = _fetch_json(PIPELINE + f'access/{group}/content.json')
			os.makedirs(store.IMAGE_DIR, exist_ok=True)
			with open(path + '.tmp', 'w') as f:
				json.dump(content, f)
			os.replace(path + '.tmp', path)
		try:
			with open(path) as f:
				keys = {k['name']: k['key'] for k in json.load(f)['keys']}
		except (OSError, ValueError, KeyError, TypeError):
			continue
		if key_id in keys:
			return base64.b64decode(keys[key_id])
	raise KeyError(f'no key {key_id}')


def _decrypt(data, sha, key_id, check=True):
	"""A capsule part: AES-128-GCM under the key_id key, IV = PBKDF2-HMAC-SHA512(its SHA-256 as
	hex, key_id, 1000, 32), as G HUB's DecryptedStream does. Checked against that SHA-256."""
	import hashlib
	try:
		from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
	except ImportError as e:
		raise ValueError('newer G HUB depots need python3-cryptography') from e
	iv = hashlib.pbkdf2_hmac('sha512', sha.encode(), key_id.encode(), 1000, 32)  # NOSONAR - G HUB's format: its files are encrypted with 1000 rounds
	plain = Cipher(algorithms.AES(_keys(key_id)), modes.GCM(iv)).decryptor().update(data)
	if check and hashlib.sha256(plain).hexdigest() != sha:
		raise ValueError('decrypted file does not match its hash')
	return plain


def _header(url):
	"""(file list, where the first file starts, key id or None) of a plain or capsule depot."""
	magic, header_len = struct.unpack('<II', _get(url, 0, 8))
	if magic == MAGIC:
		return json.loads(_get(url, 8, header_len))['files'], 8 + header_len, None
	if magic != CAPSULE:
		raise ValueError('not a G HUB depot')
	outer = json.loads(_get(url, 8, header_len))
	size = struct.unpack('<I', _get(url, 8 + header_len, 4))[0]
	inner = _decrypt(_get(url, 12 + header_len, size), outer['header-sha'], outer['key-id'])
	return json.loads(inner)['files'], 12 + header_len + size, outer['key-id']


def _files(url):
	"""{name: (offset, size[, sha, key id])} of a depot, from its header and the length before each
	file. Capsule files carry their hash and key so _read can decrypt them."""
	entries, pos, key_id = _header(url)
	files = {}
	for entry in entries:
		size = struct.unpack('<I', _get(url, pos, 4))[0]
		pos += 4
		if size == 0xFFFFFFFF:        # large file: a 64-bit length follows (ours: none seen yet)
			size = struct.unpack('<Q', _get(url, pos, 8))[0]
			pos += 8
		files[entry['name']] = (pos, size, entry['sha'], key_id) if key_id else (pos, size)
		pos += size
	return files


def _unseal(data):
	"""A sealed file (magic, header {key-id, file-sha}, length, payload) decrypted; anything else as is."""
	if len(data) < 8 or struct.unpack_from('<I', data)[0] != SEALED:
		return data
	header_len = struct.unpack_from('<I', data, 4)[0]
	header = json.loads(data[8:8 + header_len])
	size = struct.unpack_from('<I', data, 8 + header_len)[0]
	return _decrypt(data[12 + header_len:12 + header_len + size], header['file-sha'], header['key-id'])


def _read(url, entry):
	"""A depot file's bytes, decrypted when it comes from a capsule. Some capsule files (the larger
	pictures) are sealed files inside: the hash in the capsule is the one of the file within."""
	import hashlib
	data = _get(url, entry[0], entry[1])
	if len(entry) == 2:
		return data
	try:
		return _decrypt(data, entry[2], entry[3])
	except ValueError:
		inner = _unseal(_decrypt(data, entry[2], entry[3], check=False))
		if hashlib.sha256(inner).hexdigest() != entry[2]:
			raise
		return inner


def files_cached(url):
	"""_files(url), kept in the image folder after the first time: listing a large depot takes a
	request per file (over a minute for G HUB's core depot). The header's own bytes tell whether
	the depot changed."""
	import hashlib
	magic, header_len = struct.unpack('<II', _get(url, 0, 8))
	if magic not in (MAGIC, CAPSULE):
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
		chosen = _manifest_choice(model, json.loads(_read(url, files['manifest.json'])), files)
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
		if name and _to_png(_read(url, files[name]), path + '.tmp'):
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
		data = _read(url, files[name])
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
		data = _read(url, files[name])
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
		data = _read(url, files[name])
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
