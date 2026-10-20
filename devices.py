"""Which Logitech devices are connected, and what we know about each model.

CATALOG holds facts about each model (USB ids, lighting zones, whether it has onboard
profiles or a battery), taken from the openly readable part of G HUB's device list. No Logitech
files are shipped; the device itself is asked for the rest (HID++, V4L2) on its own page.

Discovery reads sysfs only, so it needs no permissions and is cheap enough to poll.
"""
import os
import re
from dataclasses import dataclass

LOGITECH = '046d'
SYS_USB = '/sys/bus/usb/devices'
SYS_HID = '/sys/bus/hid/devices'
BLUETOOTH = '0005'   # HID bus number of Bluetooth devices
# Comma-separated vid:pid (or just pid, Logitech assumed) to pretend are connected; for testing
# pages and screenshots without the hardware. pid@port pretends a real USB port holds that
# model (e.g. 082d@3-4 shows another webcam as a C920).
FAKE_ENV = 'LGHUB_FAKE_DEVICES'

# (model, name, type, USB ids, lighting zones, flags)
CATALOG = (
	('4kpro', 'BRIO 4K STREAM', 'camera', ('046d:086b',), (), ()),
	('brio', 'BRIO', 'camera', ('046d:085e',), (), ()),
	('c920', 'C920', 'camera', ('046d:082d', '046d:0892', '046d:08e5'), (), ()),
	('c922', '1080p Pro', 'camera', ('046d:085c', '046d:0883', '046d:0894'), (), ()),
	('streamcam', 'StreamCam', 'camera', ('046d:0893',), (), ()),
	('powerplay', 'POWERPLAY', 'charge_pad', ('046d:405f',), ('branding',), ()),
	('g430', 'G430', 'headset', ('046d:0a4d',), (), ()),
	('g431', 'G431', 'headset', ('046d:0a9b',), (), ()),
	('g432', 'G432', 'headset', ('046d:0a9c',), (), ()),
	('g433', 'G433', 'headset', ('046d:0a6d',), (), ()),
	('g533', 'G533', 'headset', ('046d:0a66',), (), ('battery',)),
	('g535', 'G535', 'headset', ('046d:0ac4',), (), ('battery',)),
	('g633', 'G633', 'headset', ('046d:0a5c',), ('primary', 'branding'), ('battery',)),
	('g635', 'G635', 'headset', ('046d:0a89',), ('primary', 'branding'), ('battery',)),
	('g733', 'G733', 'headset', ('046d:0ab5', '046d:0afe', '046d:0b1f'), ('top', 'bottom'), ('battery',)),
	('g735', 'G735', 'headset', ('046d:0ad8',), ('top', 'bottom', 'all'), ('battery',)),
	('g933', 'G933', 'headset', ('046d:0a5b',), ('primary', 'branding'), ('battery',)),
	('g935', 'G935', 'headset', ('046d:0a87',), ('primary', 'branding'), ('battery',)),
	('pro_71_gaming_headset', 'PRO X', 'headset', ('046d:0aaa',), (), ()),
	('pro_71_gaming_wireless_headset', 'PRO X WIRELESS', 'headset', ('046d:0aba',), (), ('battery',)),
	('pro_gaming_headset', 'PRO', 'headset', ('046d:0aa7',), (), ()),
	('ni_g435', 'G435', 'hid_device', ('046d:0acb', '046d:0adf'), (), ()),
	('g213', 'G213', 'keyboard', ('046d:c336',), ('primary',), ()),
	('g310', 'G310', 'keyboard', ('046d:aab3', '046d:c32d'), ('primary',), ()),
	('g410', 'G410', 'keyboard', ('046d:aabc', '046d:c330'), ('primary',), ('onboard',)),
	('g413', 'G413', 'keyboard', ('046d:c33a',), ('primary',), ()),
	('g512_se', 'G512', 'keyboard', ('046d:c342',), ('primary',), ()),
	('g513', 'G513', 'keyboard', ('046d:aadc', '046d:c33c'), ('primary',), ('onboard',)),
	('g610', 'G610', 'keyboard', ('046d:aacd', '046d:c333', '046d:c338'), ('primary', 'branding'), ()),
	('g613', 'G613', 'keyboard', ('046d:4065', '046d:aacd'), (), ('battery',)),
	('g810', 'G810', 'keyboard', ('046d:aabd', '046d:aacc', '046d:c331', '046d:c337'), ('primary', 'branding'), ()),
	('g815', 'G815', 'keyboard', ('046d:c33f',), ('primary', 'branding'), ('onboard',)),
	('g910', 'G910', 'keyboard', ('046d:c32b', '046d:c335'), ('primary', 'branding'), ()),
	('g915', 'G915', 'keyboard', ('046d:407c', '046d:aae3', '046d:b354', '046d:c33e'), ('primary', 'branding'), ('onboard', 'battery')),
	('g915_tkl', 'G915 TKL', 'keyboard', ('046d:408e', '046d:aafb', '046d:b35f', '046d:c343'), ('primary', 'branding'), ('onboard', 'battery')),
	('pro_keyboard', 'PRO', 'keyboard', ('046d:aadc', '046d:c339'), ('primary', 'branding'), ()),
	('yeti_classic', 'Yeti', 'microphone', ('046d:0ab7', 'b58e:9e84'), (), ()),
	('yeti_nano', 'Yeti Nano', 'microphone', ('046d:0acf', '046d:0ad0'), (), ()),
	('yeti_original_nano', 'Yeti Nano', 'microphone', ('046d:0ab1', 'b58e:0005', 'b58e:0006', 'b58e:0ab2'), (), ()),
	('yeti_x', 'Yeti X', 'microphone', ('046d:0aaf', '046d:0ad1', '046d:0aae', '046d:0ad3', 'b58e:0008'), ('primary', 'branding', 'left_side', 'right_side', 'combined', 'one', 'two', 'three', 'four', 'five', 'six', 'seven'), ()),
	('yeti_x_wow', 'Yeti X WoW® Edition', 'microphone', ('046d:0ac6', '046d:0ad2', '046d:0aae', '046d:0ad3', 'b58e:0008'), ('primary', 'branding', 'left_side', 'right_side', 'combined', 'one', 'two', 'three', 'four', 'five', 'six', 'seven'), ()),
	('g203', 'G102', 'mouse', ('046d:c084',), ('branding',), ('onboard',)),
	('g203_lightsync', 'G203 LIGHTSYNC', 'mouse', ('046d:aafd', '046d:ab28', '046d:c092', '046d:c09d'), ('branding',), ('onboard',)),
	('g302', 'G302', 'mouse', ('046d:aab5', '046d:c07f'), ('primary', 'branding'), ('onboard',)),
	('g303', 'G303', 'mouse', ('046d:aab6', '046d:c080'), ('primary', 'branding'), ('onboard',)),
	('g303_wireless', 'G303 SHROUD EDITION', 'mouse', ('046d:409e', '046d:ab11', '046d:c097'), (), ('onboard', 'battery')),
	('g305', 'G305', 'mouse', ('046d:4074',), (), ('onboard', 'battery')),
	('g402', 'G402', 'mouse', ('046d:aab4', '046d:c07e'), ('branding',), ('onboard',)),
	('g403_hero', 'G403 HERO', 'mouse', ('046d:aaf2', '046d:c08f'), ('primary', 'branding'), ('onboard',)),
	('g403_wired', 'G403', 'mouse', ('046d:c083',), ('primary', 'branding'), ('onboard',)),
	('g403_wireless', 'G403', 'mouse', ('046d:405d', '046d:c082'), ('primary', 'branding'), ('onboard', 'battery')),
	('g502_core', 'G502', 'mouse', ('046d:aab3', '046d:c07d'), ('branding',), ('onboard',)),
	('g502_hero', 'G502 HERO', 'mouse', ('046d:aae6', '046d:c08b'), ('primary', 'branding'), ('onboard',)),
	('g502_spectrum', 'G502', 'mouse', ('046d:c332',), ('primary', 'branding'), ('onboard',)),
	('g502_wireless', 'G502 LIGHTSPEED', 'mouse', ('046d:407f', '046d:aaef', '046d:c08d'), ('primary', 'branding'), ('onboard', 'battery')),
	('g600', 'G600', 'mouse', ('046d:c24a',), ('primary',), ('onboard',)),
	('g602', 'G602', 'mouse', ('046d:c537',), (), ('onboard', 'battery')),
	('g603', 'G603', 'mouse', ('046d:406c',), (), ('onboard', 'battery')),
	('g604', 'G604 LIGHTSPEED', 'mouse', ('046d:4085', '046d:b024'), (), ('onboard', 'battery')),
	('g703', 'G703', 'mouse', ('046d:4070', '046d:c087'), ('primary', 'branding'), ('onboard', 'battery')),
	('g703_hero', 'G703 LIGHTSPEED', 'mouse', ('046d:4086', '046d:aaf6', '046d:c090'), ('primary', 'branding'), ('onboard', 'battery')),
	('g900', 'G900', 'mouse', ('046d:4053', '046d:aaba', '046d:c081'), ('primary', 'branding'), ('onboard', 'battery')),
	('g903', 'G903', 'mouse', ('046d:4067', '046d:aad8', '046d:c086'), ('primary', 'branding'), ('onboard', 'battery')),
	('g903_hero', 'G903 LIGHTSPEED', 'mouse', ('046d:4087', '046d:aaf7', '046d:c091'), ('primary', 'branding'), ('onboard', 'battery')),
	('mx518', 'MX518', 'mouse', ('046d:c08e',), (), ('onboard',)),
	('pro_mouse', 'PRO', 'mouse', ('046d:c085',), ('branding',), ('onboard',)),
	('pro_mouse_hero', 'PRO HERO', 'mouse', ('046d:aae7', '046d:c08c'), ('branding',), ('onboard',)),
	('pro_wireless_mouse', 'PRO WIRELESS', 'mouse', ('046d:4079', '046d:aadf', '046d:c088'), ('primary', 'branding'), ('onboard', 'battery')),
	('pro_x_wireless_mouse', 'PRO X SUPERLIGHT', 'mouse', ('046d:4093', '046d:ab00', '046d:c094'), (), ('onboard', 'battery')),
	('g560', 'G560', 'speaker', ('046d:0a78',), ('one', 'two', 'three', 'four'), ()),
)

# Wireless receivers: the devices paired to them are found over HID++ (later).
LIGHTSPEED = 'LIGHTSPEED Receiver'
RECEIVERS = {
	'046d:c52b': 'Unifying Receiver',
	'046d:c539': LIGHTSPEED,
	'046d:c53a': LIGHTSPEED,
	'046d:c53f': LIGHTSPEED,
	'046d:c541': LIGHTSPEED,
	'046d:c545': LIGHTSPEED,
	'046d:c547': LIGHTSPEED,
	'046d:c548': 'Bolt Receiver',
}

TYPE_NAMES = {
	'mouse': 'Mouse', 'keyboard': 'Keyboard', 'headset': 'Headset', 'camera': 'Webcam',
	'microphone': 'Microphone', 'speaker': 'Speakers', 'charge_pad': 'Charging pad',
	'hid_device': 'Headset', 'receiver': 'Receiver', 'other': 'Device',
}
TYPE_ICONS = {
	'mouse': 'input-mouse-symbolic', 'keyboard': 'input-keyboard-symbolic',
	'headset': 'audio-headset-symbolic', 'hid_device': 'audio-headset-symbolic',
	'camera': 'camera-web-symbolic', 'microphone': 'audio-input-microphone-symbolic',
	'speaker': 'audio-speakers-symbolic', 'charge_pad': 'battery-full-charging-symbolic',
	'receiver': 'network-wireless-symbolic', 'other': 'input-gaming-symbolic',
}

# Headsets with Blue VO!CE (G HUB has presets for them) -> their preset set in store.GHUB_PRESETS.
BLUE_VOICE_MODELS = {'pro_71_gaming_headset': 'wired', 'pro_71_gaming_wireless_headset': 'wireless',
                     'g733': 'g733'}


@dataclass(frozen=True)
class Model:
	key: str
	name: str
	type: str
	usb_ids: tuple
	lighting: tuple
	flags: tuple


@dataclass(frozen=True)
class Device:
	id: str          # stable while connected: usb:<port>, usb:<port>#<slot> behind a receiver, or
	                 # bt:<HID device name> over Bluetooth
	usb_id: str      # vid:pid (of the receiver, for a paired device; the Bluetooth one over Bluetooth)
	model: Model
	serial: str = ''
	index: int = 0xFF   # HID++ device index: 0xFF corded, 1-6 paired to a receiver

	@property
	def port(self):
		return self.id.split(':', 1)[1].split('#')[0]

	@property
	def wireless(self):
		return self.index != 0xFF

	@property
	def bluetooth(self):
		return self.id.startswith('bt:')

	@property
	def link(self):
		"""How it's connected, for labels: 'wireless' (through a receiver), 'Bluetooth' or 'USB'."""
		if self.wireless:
			return 'wireless'
		return 'Bluetooth' if self.bluetooth else 'USB'

	@property
	def name(self):
		return self.model.name

	@property
	def type_name(self):
		return TYPE_NAMES.get(self.model.type, TYPE_NAMES['other'])

	@property
	def icon(self):
		return TYPE_ICONS.get(self.model.type, TYPE_ICONS['other'])


MODELS = tuple(Model(*row) for row in CATALOG)
_BY_USB_ID = {}
for _m in MODELS:
	for _usb in _m.usb_ids:
		_BY_USB_ID.setdefault(_usb, _m)


def model_for(usb_id):
	"""The catalog model for a vid:pid, a receiver, a generic Logitech device, or None."""
	if usb_id in _BY_USB_ID:
		return _BY_USB_ID[usb_id]
	if usb_id in RECEIVERS:
		return Model('receiver', RECEIVERS[usb_id], 'receiver', (usb_id,), (), ())
	if usb_id.startswith(LOGITECH + ':'):
		return Model(unknown_key(usb_id), f'Logitech device {usb_id}', 'other', (usb_id,), (), ())
	return None


def unknown_key(text):
	"""A model key for a device the catalog doesn't know, its own per device name or id, so its
	saved settings never mix with another unknown device's."""
	return 'unknown_' + (re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_') or 'device')


def is_unknown(model):
	return model.key.startswith('unknown')


def _read(path):
	try:
		with open(path) as f:
			return f.read().strip()
	except OSError:
		return ''


def _usb_devices():
	"""[(port path, vid:pid, serial, product name)] for every USB device (not interfaces or root hubs)."""
	try:
		names = sorted(os.listdir(SYS_USB))
	except OSError:
		return []
	found = []
	for name in names:
		if ':' in name or name.startswith('usb'):
			continue
		base = os.path.join(SYS_USB, name)
		vid, pid = _read(os.path.join(base, 'idVendor')), _read(os.path.join(base, 'idProduct'))
		if vid and pid:
			found.append((name, f'{vid}:{pid}'.lower(), _read(os.path.join(base, 'serial')), _read(os.path.join(base, 'product'))))
	return found


def _bluetooth_devices():
	"""[(HID device name, vid:pid, address, name)] for each Logitech device connected over
	Bluetooth, one entry per device."""
	try:
		names = sorted(os.listdir(SYS_HID))
	except OSError:
		return []
	found, seen = [], set()
	for name in names:
		bus, vid, rest = (name.split(':') + ['', ''])[:3]
		if bus != BLUETOOTH or vid.lower() != LOGITECH:
			continue
		lines = _read(os.path.join(SYS_HID, name, 'uevent')).splitlines()
		info = {key: value for key, _, value in (line.partition('=') for line in lines)}
		address = info.get('HID_UNIQ', name)
		if address not in seen:
			seen.add(address)
			found.append((name, f'{LOGITECH}:{rest.split(".")[0]}'.lower(), address, info.get('HID_NAME', '')))
	return found


def _fake_devices():
	found = []
	for i, item in enumerate(filter(None, (s.strip().lower() for s in os.environ.get(FAKE_ENV, '').split(',')))):
		item, _, port = item.partition('@')
		usb_id = item if ':' in item else f'{LOGITECH}:{item}'
		found.append((port or f'fake{i}', usb_id, '', ''))
	return found


def discover():
	"""Connected devices we know or that are Logitech's, in a stable order."""
	devices = []
	for port, usb_id, serial, product in _usb_devices() + _fake_devices():
		model = model_for(usb_id)
		if model and is_unknown(model) and product:   # not in the catalog: the name it gives itself
			model = match_model(product, 'other', fallback=model)
		if model:
			devices.append(Device(f'usb:{port}', usb_id, model, serial))
	for hid_name, usb_id, address, name in _bluetooth_devices():
		# the Bluetooth product id if the catalog has it, else the name the device gives itself
		model = _BY_USB_ID.get(usb_id) or match_model(name or f'Logitech device {usb_id}', 'other')
		devices.append(Device(f'bt:{hid_name}', usb_id, model, address))
	return devices


def _transport(device):
	"""(transport, report ids) for the HID++ interface a device is reached through."""
	import hidpp
	import simulate
	if device.port.startswith('fake') or os.environ.get(FAKE_ENV):
		transport = simulate.transport_for(device.usb_id, device.port)
		if transport is None:
			raise OSError('no simulated HID++ device for this model')
		return transport, {hidpp.LONG}
	return hidpp.open_receiver(device.port)


def open_hidpp(device):
	"""A hidpp.Device for a connected (or simulated) device; raises OSError if there is none."""
	import hidpp
	if device.port.startswith('fake') or os.environ.get(FAKE_ENV):
		transport, reports = _transport(device)
		return hidpp.Device(transport, device.index, reports)
	return hidpp.open_usb(device.port, device.index)


KIND_TYPES = {'mouse': 'mouse', 'trackball': 'mouse', 'touchpad': 'mouse', 'keyboard': 'keyboard',
              'numpad': 'keyboard', 'headset': 'headset', 'speaker': 'speaker', 'microphone': 'microphone'}


# Words that can follow a model's name in a device's own name without making it another model
# ("G915 TKL LIGHTSPEED Wireless RGB Keyboard" is a G915 TKL; "G502 X PLUS" is not a G502)
NAME_WORDS = frozenset(('LIGHTSPEED', 'WIRELESS', 'GAMING', 'MOUSE', 'KEYBOARD', 'HEADSET', 'RGB',
                        'MECHANICAL', 'RECEIVER', 'SPEAKERS', 'MICROPHONE', 'WEBCAM', 'LOGITECH'))


def _names(text, name):
	"""Whether a device's own name (upper case) is this model's name and not a longer model's."""
	for m in re.finditer(re.escape(name), text):
		if m.start() and text[m.start() - 1].isalnum():
			continue
		after = re.match(r'\W*(\w*)', text[m.end():]).group(1)
		if not after or after in NAME_WORDS:
			return True
	return False


def match_model(name, kind, fallback=None):
	"""The catalog model a device's own name names (longest wins), else fallback, else a model of
	its own under that name."""
	dev_type = KIND_TYPES.get(kind, 'other')
	text = name.upper()
	best = None
	for m in MODELS:
		if (m.type == dev_type or dev_type == 'other') and _names(text, m.name.upper()):
			if best is None or len(m.name) > len(best.name):
				best = m
	if best:
		return best
	if fallback:
		return Model(fallback.key, name or fallback.name, fallback.type, fallback.usb_ids, (), ())
	return Model(unknown_key(name or 'wireless'), name or 'Wireless device', dev_type, (), (), ())


def scan_receiver(receiver):
	"""Devices paired to a receiver and switched on, as Device entries. Talks to the receiver;
	call from a worker thread."""
	import features
	import hidpp
	transport, reports = _transport(receiver)
	try:
		paired = features.paired_devices(lambda index: hidpp.Device(transport, index, reports))
	finally:
		if not receiver.port.startswith('fake') and not os.environ.get(FAKE_ENV):
			transport.close()
	return [Device(f'{receiver.id}#{p.index}', receiver.usb_id, match_model(p.name, p.kind), receiver.serial, p.index)
	        for p in paired]


def blue_voice_model(device):
	"""The device's Blue VO!CE preset set if it has Blue VO!CE, else None."""
	return BLUE_VOICE_MODELS.get(device.model.key) if device else None
