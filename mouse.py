"""Mice over HID++ 2.0: DPI, report rate, buttons and lighting in onboard profiles.

G HUB keeps a mouse's settings in its onboard memory (feature 0x8100), so they work on any
computer without software running. We do the same: read a profile sector, change it, write it
back with its checksum, and read it again to check. The first write keeps a backup of every
sector we touch (in ~/.local/share/lghub/backups).

Mice without onboard memory get live settings through 0x2201 (DPI) and 0x8060 (report rate).
"""
import os
import struct
from dataclasses import dataclass, field

import hidpp
import store

DPI = 0x2201
REPORT_RATE = 0x8060
EXT_DPI = 0x2202
EXTENDED_RATE = 0x8061
# 0x8061's rate numbers, as G HUB maps them (Feature8061AdjustableReportRate): n -> Hz
EXTENDED_RATES = (125, 250, 500, 1000, 2000, 4000, 8000)
ONBOARD = 0x8100
SMARTSHIFT, SMARTSHIFT_TORQUE = 0x2110, 0x2111
FREE_SPIN, RATCHET, ALWAYS_RATCHET = 1, 2, 0xFF

MODE_ONBOARD, MODE_HOST = 1, 2
DIRECTORY = 0x0000
ROM = 0x0100           # factory profiles: sector ROM | n, read only
CHUNK = 16
BACKUP_DIR = os.path.join(store.DATA_DIR, 'backups')

# Profile sector layout (all offsets in bytes).
P_RATE, P_DEFAULT_DPI, P_SHIFT_DPI, P_DPI = 0, 1, 2, 3
DPI_SLOTS = 5
P_BUTTONS, P_SHIFTED_BUTTONS, BUTTON_SLOTS = 32, 96, 16
P_NAME, NAME_BYTES = 160, 48
P_LEDS, LED_SIZE = 208, 11
LED_SLOTS = 2

# --- button actions ------------------------------------------------------------------------

B_MACRO, B_HID, B_SPECIAL, B_DISABLED = 0x00, 0x80, 0x90, 0xFF
HID_MOUSE, HID_KEY, HID_CONSUMER = 0x01, 0x02, 0x03

MOUSE_BUTTONS = {0x0001: 'Left click', 0x0002: 'Right click', 0x0004: 'Middle click',
                 0x0008: 'Back', 0x0010: 'Forward'}
SPECIALS = {0x01: 'Scroll left', 0x02: 'Scroll right', 0x03: 'DPI up', 0x04: 'DPI down',
            0x05: 'DPI cycle', 0x06: 'DPI default', 0x07: 'DPI shift', 0x08: 'Next profile',
            0x09: 'Previous profile', 0x0a: 'Cycle profiles', 0x0b: 'G-Shift', 0x0c: 'Battery level'}
CONSUMER = {0x00e9: 'Volume up', 0x00ea: 'Volume down', 0x00e2: 'Mute', 0x00cd: 'Play / pause',
            0x00b5: 'Next track', 0x00b6: 'Previous track', 0x00b7: 'Stop'}
MODIFIERS = ((0x01, 'Ctrl'), (0x02, 'Shift'), (0x04, 'Alt'), (0x08, 'Super'),
             (0x10, 'Right Ctrl'), (0x20, 'Right Shift'), (0x40, 'AltGr'), (0x80, 'Right Super'))


def _key_names():
	names = {0x04 + i: chr(ord('A') + i) for i in range(26)}
	names.update({0x1e + i: str((i + 1) % 10) for i in range(10)})
	names.update({0x3a + i: f'F{i + 1}' for i in range(12)})
	names.update({0x68 + i: f'F{i + 13}' for i in range(12)})
	names.update({0x28: 'Enter', 0x29: 'Esc', 0x2a: 'Backspace', 0x2b: 'Tab', 0x2c: 'Space',
	              0x2d: '-', 0x2e: '=', 0x2f: '[', 0x30: ']', 0x31: '\\', 0x33: ';', 0x34: "'",
	              0x35: '`', 0x36: ',', 0x37: '.', 0x38: '/', 0x39: 'Caps Lock', 0x46: 'Print Screen',
	              0x47: 'Scroll Lock', 0x48: 'Pause', 0x49: 'Insert', 0x4a: 'Home', 0x4b: 'Page Up',
	              0x4c: 'Delete', 0x4d: 'End', 0x4e: 'Page Down', 0x4f: 'Right', 0x50: 'Left',
	              0x51: 'Down', 0x52: 'Up', 0x65: 'Menu'})
	return names


KEY_NAMES = _key_names()


@dataclass
class Action:
	"""One button binding: 4 bytes in the profile. Unknown kinds keep their bytes."""
	raw: bytes

	@property
	def kind(self):
		return self.raw[0]

	def describe(self):
		k, a, b, c = self.raw
		if self.raw == b'\xff\xff\xff\xff' or k == B_DISABLED:
			return 'Disabled'
		if k == B_HID and a == HID_MOUSE:
			mask = (b << 8) | c
			return MOUSE_BUTTONS.get(mask, f'Mouse button {mask.bit_length()}')
		if k == B_HID and a == HID_KEY:
			mods = [n for bit, n in MODIFIERS if b & bit]
			key = KEY_NAMES.get(c, f'Key 0x{c:02x}') if c else ''
			return ' + '.join(mods + ([key] if key else [])) or 'Key'
		if k == B_HID and a == HID_CONSUMER:
			usage = (b << 8) | c
			return CONSUMER.get(usage, f'Media key 0x{usage:04x}')
		if k == B_SPECIAL:
			return SPECIALS.get(a, f'Special 0x{a:02x}')
		if k == B_MACRO:
			return 'Macro'
		return 'Other'

	@staticmethod
	def mouse(mask):
		return Action(bytes([B_HID, HID_MOUSE, mask >> 8, mask & 0xFF]))

	@staticmethod
	def key(modifiers, usage):
		return Action(bytes([B_HID, HID_KEY, modifiers, usage]))

	@staticmethod
	def consumer(usage):
		return Action(bytes([B_HID, HID_CONSUMER, usage >> 8, usage & 0xFF]))

	@staticmethod
	def special(code):
		return Action(bytes([B_SPECIAL, code, 0, 0]))

	@staticmethod
	def disabled():
		return Action(b'\xff\xff\xff\xff')


# The choices offered in the button editor (keystrokes are recorded separately).
PRESET_ACTIONS = (
	[(name, Action.mouse(mask)) for mask, name in MOUSE_BUTTONS.items()]
	+ [(name, Action.special(code)) for code, name in SPECIALS.items() if code != 0x0c]
	+ [(name, Action.consumer(usage)) for usage, name in CONSUMER.items()]
	+ [('Disabled', Action.disabled())]
)

# --- lighting ------------------------------------------------------------------------------

LED_OFF, LED_FIXED, LED_CYCLE, LED_BREATHING = 0x00, 0x01, 0x03, 0x0a
LED_EFFECTS = {LED_OFF: 'Off', LED_FIXED: 'Fixed', LED_BREATHING: 'Breathing', LED_CYCLE: 'Color cycle'}


@dataclass
class Led:
	"""One lighting zone's effect: 11 bytes in the profile."""
	raw: bytes

	@property
	def effect(self):
		return self.raw[0]

	@property
	def color(self):
		return tuple(self.raw[1:4]) if self.effect in (LED_FIXED, LED_BREATHING) else (0x2f, 0x8c, 0xff)

	@property
	def period(self):
		"""Milliseconds per cycle / breath."""
		if self.effect == LED_CYCLE:
			return struct.unpack('>H', self.raw[6:8])[0] or 10000
		if self.effect == LED_BREATHING:
			return struct.unpack('>H', self.raw[4:6])[0] or 3000
		return 3000

	@property
	def brightness(self):
		"""1-100 %. The device stores 0 for full."""
		if self.effect == LED_CYCLE:
			value = self.raw[8]
		elif self.effect == LED_BREATHING:
			value = self.raw[7]
		else:
			value = 100
		return value if 0 < value <= 100 else 100

	@staticmethod
	def build(effect, color=(255, 255, 255), period=3000, brightness=100):
		r, g, b = color
		period = max(1000, min(20000, int(period)))
		brightness = max(1, min(100, int(brightness)))
		if effect == LED_FIXED:
			data = bytes([LED_FIXED, r, g, b, 0])
		elif effect == LED_BREATHING:
			data = bytes([LED_BREATHING, r, g, b]) + struct.pack('>H', period) + bytes([0, brightness])
		elif effect == LED_CYCLE:
			data = bytes([LED_CYCLE, 0, 0, 0, 0, 0]) + struct.pack('>H', period) + bytes([brightness])
		else:
			data = bytes([LED_OFF])
		return Led(data.ljust(LED_SIZE, b'\0'))


# --- profiles ------------------------------------------------------------------------------

def crc_ccitt(data):
	crc = 0xFFFF
	for byte in data:
		crc ^= byte << 8
		for _ in range(8):
			crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
			crc &= 0xFFFF
	return crc


def crc_ok(sector):
	return struct.unpack('>H', sector[-2:])[0] == crc_ccitt(sector[:-2])


def with_crc(sector):
	return bytes(sector[:-2]) + struct.pack('>H', crc_ccitt(sector[:-2]))


@dataclass
class Profile:
	"""One onboard profile. Edits change `data`; `original` is what the mouse holds."""
	number: int            # 1-based, as the mouse counts them
	sector: int
	enabled: bool
	data: bytearray
	original: bytes = b''
	buttons: int = BUTTON_SLOTS

	@property
	def dirty(self):
		return bytes(self.data) != self.original

	@property
	def name(self):
		raw = bytes(self.data[P_NAME:P_NAME + NAME_BYTES])
		if raw[:2] in (b'\xff\xff', b'\0\0'):
			return f'Profile {self.number}'
		text = raw.decode('utf-16-le', 'replace').split('\0')[0].split('\uffff')[0].strip()
		return text or f'Profile {self.number}'

	@name.setter
	def name(self, text):
		raw = text[:NAME_BYTES // 2 - 1].encode('utf-16-le')
		self.data[P_NAME:P_NAME + NAME_BYTES] = raw.ljust(NAME_BYTES, b'\0')

	@property
	def report_rate(self):
		"""Reports per second."""
		ms = self.data[P_RATE]
		return 1000 // ms if ms and ms != 0xFF else 1000

	@report_rate.setter
	def report_rate(self, hz):
		self.data[P_RATE] = max(1, round(1000 / hz))

	@property
	def dpi_levels(self):
		"""Five slots; 0 = unused."""
		out = []
		for i in range(DPI_SLOTS):
			value = struct.unpack_from('<H', self.data, P_DPI + 2 * i)[0]
			out.append(0 if value in (0, 0xFFFF) else value)
		return out

	def set_dpi(self, slot, value):
		struct.pack_into('<H', self.data, P_DPI + 2 * slot, value)

	@property
	def default_dpi(self):
		return self.data[P_DEFAULT_DPI] if self.data[P_DEFAULT_DPI] < DPI_SLOTS else 0

	@default_dpi.setter
	def default_dpi(self, slot):
		self.data[P_DEFAULT_DPI] = slot

	@property
	def shift_dpi(self):
		return self.data[P_SHIFT_DPI] if self.data[P_SHIFT_DPI] < DPI_SLOTS else 0

	@shift_dpi.setter
	def shift_dpi(self, slot):
		self.data[P_SHIFT_DPI] = slot

	def button(self, i, shifted=False):
		base = P_SHIFTED_BUTTONS if shifted else P_BUTTONS
		return Action(bytes(self.data[base + 4 * i:base + 4 * i + 4]))

	def set_button(self, i, action, shifted=False):
		base = P_SHIFTED_BUTTONS if shifted else P_BUTTONS
		self.data[base + 4 * i:base + 4 * i + 4] = action.raw

	def led(self, i):
		return Led(bytes(self.data[P_LEDS + LED_SIZE * i:P_LEDS + LED_SIZE * (i + 1)]))

	def set_led(self, i, led):
		self.data[P_LEDS + LED_SIZE * i:P_LEDS + LED_SIZE * (i + 1)] = led.raw

	def revert(self):
		self.data[:] = self.original


@dataclass
class Sensor:
	"""What 0x2201 says about the sensor: the DPI values it accepts."""
	values: list = field(default_factory=list)   # explicit values, when it lists them
	low: int = 100
	high: int = 25600
	step: int = 50

	def clamp(self, dpi):
		if self.values:
			return min(self.values, key=lambda v: abs(v - dpi))
		dpi = max(self.low, min(self.high, int(dpi)))
		return self.low + round((dpi - self.low) / self.step) * self.step


def _ext_sensor(values, steps):
	if not values:
		return Sensor()
	if steps:
		return Sensor([], min(values), max(values), max(1, steps[0]))
	return Sensor(sorted(values), min(values), max(values), 1)


def parse_dpi_list(words):
	"""0x2201 lists DPI values; a word 0xE0nn means 'every nn DPI from the previous to the next'."""
	values, ranges = [], []
	for i, w in enumerate(words):
		if w == 0:
			break
		if w >> 13 == 0b111:
			if values and i + 1 < len(words):
				ranges.append((values.pop(), words[i + 1], w & 0x1FFF))
			continue
		if ranges and w == ranges[-1][1]:
			continue
		values.append(w)
	if ranges:
		low, high, step = ranges[0]
		return Sensor([], low, high, max(1, step))
	if values:
		return Sensor(sorted(values), values[0], values[-1], 1)
	return Sensor()


class Mouse:
	"""Everything the mouse page needs. Every method talks to the device: call from a worker
	thread, never from the GTK main loop."""

	def __init__(self, dev, ident):
		self.dev = dev
		self.ident = ident                # for backups: serial or usb port
		self.features = dev.feature_list()
		self.name = dev.name()
		self.firmware = dev.firmware()
		self.sensor = self._read_sensor() if DPI in self.features or EXT_DPI in self.features else None
		self.rates = self._read_rates() if REPORT_RATE in self.features or EXTENDED_RATE in self.features else []
		self.onboard = ONBOARD in self.features
		self.profiles = []
		self.sector_size = 0
		self.button_count = 0
		self.directory_valid = False
		if self.onboard:
			self._read_description()

	# --- live (host mode) -----------------------------------------------------------------

	# 0x2202 (newer mice), as G HUB's Feature2202ExtendedAdjustableDPI: fn 1 GetSensorCapabilities
	# (byte 2: bit 0 = its own Y DPI, bit 1 = lift-off setting), fn 2 GetSensorDpiRanges (sensor,
	# axis, page -> the same three bytes, then 16-bit words: 0xE0nn = step nn, others DPI values,
	# 0 = end), fn 5 GetSensorDpiParameters (sensor, DPI X, default X, DPI Y, default Y, lift-off),
	# fn 6 SetSensorDpiParameters (sensor, DPI X, DPI Y or 0, lift-off or 0). Sensor 0, X axis;
	# Y follows X (ours).

	def _read_sensor(self):
		if EXT_DPI in self.features:
			return self._read_ext_sensor()
		r = self.dev.call(DPI, 1, b'\0')
		words = [struct.unpack('>H', r[1 + 2 * i:3 + 2 * i])[0] for i in range(7)]
		return parse_dpi_list(words)

	def _read_ext_sensor(self):
		values, steps = [], []
		for page in range(16):
			r = self.dev.call(EXT_DPI, 2, bytes([0, 0, page]))
			words = [struct.unpack('>H', r[i:i + 2])[0] for i in range(3, 15, 2)]
			for w in words:
				if w == 0:
					return _ext_sensor(values, steps)
				(steps if w >> 8 == 0xE0 else values).append(w & 0xFF if w >> 8 == 0xE0 else w)
		return _ext_sensor(values, steps)

	def current_dpi(self):
		if EXT_DPI in self.features:
			return struct.unpack('>H', self.dev.call(EXT_DPI, 5, b'\0')[1:3])[0]
		r = self.dev.call(DPI, 2, b'\0')
		return struct.unpack('>H', r[1:3])[0]

	def set_dpi(self, value):
		if EXT_DPI in self.features:
			caps = self.dev.call(EXT_DPI, 1, b'\0')[2]
			lod = self.dev.call(EXT_DPI, 5, b'\0')[9] if caps & 2 else 0
			y = value if caps & 1 else 0
			self.dev.call(EXT_DPI, 6, b'\0' + struct.pack('>HH', value, y) + bytes([lod]))
			return
		self.dev.call(DPI, 3, b'\0' + struct.pack('>H', value))

	# --- scroll wheel (SmartShift, 0x2110 / 0x2111), as G HUB's Feature2111SmartShiftAndTorque
	# drives it: mode 1 = free spin, 2 = ratchet; auto-disengage 0xFF = always ratchet (SmartShift
	# off), otherwise the speed at which it lets go (G HUB maps its slider to 4 + (speed - min) /
	# step with per-model numbers we don't have, so the device's own value is shown); torque on
	# 0x2111 only, 1 (G HUB's default) up to the device's maximum.

	def wheel(self):
		"""{'mode', 'auto', 'torque', 'max_torque'}, or None without SmartShift."""
		if SMARTSHIFT_TORQUE in self.features:
			caps = self.dev.call(SMARTSHIFT_TORQUE, 0)
			r = self.dev.call(SMARTSHIFT_TORQUE, 1)
			return {'mode': r[0], 'auto': r[1], 'torque': r[2], 'max_torque': caps[3] or 100}
		if SMARTSHIFT in self.features:
			r = self.dev.call(SMARTSHIFT, 0)
			return {'mode': r[0], 'auto': r[1], 'torque': None, 'max_torque': None}
		return None

	def set_wheel(self, mode, auto, torque=None):
		if SMARTSHIFT_TORQUE in self.features:
			self.dev.call(SMARTSHIFT_TORQUE, 2, bytes([mode, auto, max(1, torque or 1)]))
		else:
			self.dev.call(SMARTSHIFT, 1, bytes([mode, auto]))

	# 0x8061 (newer mice, up to 8 kHz): fn 1 GetActualReportRateList (byte 1: bit n = rate n),
	# fn 2 GetReportRate (byte 0: rate number; the request byte, 0 here, is ours), fn 3 SetReportRate.

	def _read_rates(self):
		if EXTENDED_RATE in self.features:
			mask = self.dev.call(EXTENDED_RATE, 1)[1]
			return sorted((hz for n, hz in enumerate(EXTENDED_RATES) if mask >> n & 1), reverse=True)
		mask = self.dev.call(REPORT_RATE, 0)[0]
		return sorted((1000 // (bit + 1) for bit in range(8) if mask >> bit & 1), reverse=True)

	def current_rate(self):
		if EXTENDED_RATE in self.features:
			n = self.dev.call(EXTENDED_RATE, 2, b'\0')[0]
			return EXTENDED_RATES[n] if n < len(EXTENDED_RATES) else 0
		ms = self.dev.call(REPORT_RATE, 1)[0]
		return 1000 // ms if ms else 0

	def set_rate(self, hz):
		if EXTENDED_RATE in self.features:
			self.dev.call(EXTENDED_RATE, 3, bytes([EXTENDED_RATES.index(hz)]))
			return
		self.dev.call(REPORT_RATE, 2, bytes([round(1000 / hz)]))

	# --- onboard memory -------------------------------------------------------------------

	def _read_description(self):
		r = self.dev.call(ONBOARD, 0)
		self.profile_count = r[3]
		self.rom_profile_count = r[4]
		self.button_count = min(r[5], BUTTON_SLOTS)
		self.sector_size = struct.unpack('>H', r[7:9])[0]

	def mode(self):
		return self.dev.call(ONBOARD, 2)[0]

	def set_mode(self, mode):
		self.dev.call(ONBOARD, 1, bytes([mode]))

	def current_profile(self):
		return self.dev.call(ONBOARD, 4)[1]

	def set_current_profile(self, number):
		self.dev.call(ONBOARD, 3, bytes([0, number]))

	def current_dpi_slot(self):
		return self.dev.call(ONBOARD, 11)[0]

	def set_current_dpi_slot(self, slot):
		self.dev.call(ONBOARD, 12, bytes([slot]))

	def read_sector(self, sector):
		size = self.sector_size
		out = bytearray(size)
		offset = 0
		while offset < size:
			at = min(offset, size - CHUNK)       # the device won't read past the end
			chunk = self.dev.call(ONBOARD, 5, struct.pack('>HH', sector, at))
			out[at:at + CHUNK] = chunk[:CHUNK]
			offset = at + CHUNK
		return bytes(out)

	def _write_sector(self, sector, data):
		data = with_crc(data)
		self.dev.call(ONBOARD, 6, struct.pack('>HHH', sector, 0, len(data)))
		for at in range(0, len(data), CHUNK):
			self.dev.call(ONBOARD, 7, data[at:at + CHUNK].ljust(CHUNK, b'\xff'))
		self.dev.call(ONBOARD, 8)
		if self.read_sector(sector) != data:
			raise IOError(f'sector 0x{sector:04x} did not read back as written')
		return data

	def load_profiles(self):
		"""Read the directory and every profile. Without a valid directory the mouse runs its
		factory profiles; those are shown, and saving copies them to user memory."""
		directory = self.read_sector(DIRECTORY)
		entries = []
		self.directory_valid = crc_ok(directory)
		if self.directory_valid:
			for i in range(0, len(directory) - 2, 4):
				sector = struct.unpack('>H', directory[i:i + 2])[0]
				if sector == 0xFFFF:
					break
				entries.append((sector, bool(directory[i + 2])))
		else:
			entries = [(ROM | n, True) for n in range(1, (self.rom_profile_count or self.profile_count) + 1)]
		self.profiles = []
		for number, (sector, enabled) in enumerate(entries[:self.profile_count], start=1):
			data = self.read_sector(sector)
			self.profiles.append(Profile(number, sector, enabled, bytearray(data), data, self.button_count))
		return self.profiles

	def _backup(self, sector, data):
		folder = os.path.join(BACKUP_DIR, ''.join(c if c.isalnum() else '_' for c in self.ident))
		path = os.path.join(folder, f'sector_{sector:04x}.bin')
		if not os.path.exists(path):
			os.makedirs(folder, exist_ok=True)
			with open(path, 'wb') as f:
				f.write(data)

	def save(self, profiles):
		"""Write the changed profiles (and the directory, if it changes)."""
		self._backup(DIRECTORY, self.read_sector(DIRECTORY))
		directory_changed = False
		for p in profiles:
			if p.sector & ROM:                   # factory profile: give it a user sector
				p.sector = p.number
				directory_changed = True
			elif not p.dirty:
				continue
			self._backup(p.sector, p.original or self.read_sector(p.sector))
			written = self._write_sector(p.sector, bytes(p.data))
			p.data[:] = written
			p.original = written
		if directory_changed or not self.directory_valid:
			table = b''.join(struct.pack('>HBB', p.sector, int(p.enabled), 0) for p in profiles)
			table = (table + b'\xff\xff').ljust(self.sector_size, b'\xff')
			self._write_sector(DIRECTORY, table)
			self.directory_valid = True
