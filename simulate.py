"""Pretend HID++ devices, for trying pages without the hardware (LGHUB_FAKE_DEVICES) and for
the tests. They follow the protocol as hidpp.py and mouse.py use it; they are not a record of
any real device's answers."""
import struct
import zlib

import features
import hidpp
import mouse

SECTOR = 255


def _profile(number, dpis, color):
	data = bytearray(b'\xff' * SECTOR)
	data[mouse.P_RATE] = 1
	data[mouse.P_DEFAULT_DPI] = 1
	data[mouse.P_SHIFT_DPI] = 0
	for i in range(mouse.DPI_SLOTS):
		struct.pack_into('<H', data, mouse.P_DPI + 2 * i, dpis[i] if i < len(dpis) else 0)
	defaults = [mouse.Action.mouse(m) for m in mouse.MOUSE_BUTTONS] + [
		mouse.Action.special(0x01), mouse.Action.special(0x02), mouse.Action.special(0x07),
		mouse.Action.special(0x03), mouse.Action.special(0x04), mouse.Action.special(0x0a)]
	for i, action in enumerate(defaults):
		data[mouse.P_BUTTONS + 4 * i:mouse.P_BUTTONS + 4 * i + 4] = action.raw
	data[mouse.P_NAME:mouse.P_NAME + mouse.NAME_BYTES] = f'Profile {number}'.encode('utf-16-le').ljust(48, b'\0')
	data[mouse.P_LEDS:mouse.P_LEDS + 11] = mouse.Led.build(mouse.LED_FIXED, color).raw
	data[mouse.P_LEDS + 11:mouse.P_LEDS + 22] = mouse.Led.build(mouse.LED_BREATHING, color, 4000, 80).raw
	return mouse.with_crc(bytes(data))


class FakeMouse:
	"""A corded G502 HERO-like mouse with factory profiles only (empty user memory)."""
	FEATURES = [hidpp.ROOT, hidpp.FEATURE_SET, hidpp.FIRMWARE, hidpp.NAME, mouse.DPI,
	            mouse.REPORT_RATE, mouse.ONBOARD, 0x8110]
	KIND = 3   # mouse

	def __init__(self, name='G502 HERO Gaming Mouse'):
		self.device_name = name.encode()
		if 'LIGHTSPEED' in name:
			self.FEATURES = self.FEATURES + [features.UNIFIED_BATTERY]
		self.memory = {mouse.ROM | 1: _profile(1, [400, 800, 1600, 3200, 6400], (0, 140, 255)),
		               mouse.ROM | 2: _profile(2, [1200, 2400], (255, 60, 0)),
		               mouse.ROM | 3: _profile(3, [800], (60, 255, 120))}
		self.mode, self.profile, self.dpi_slot, self.dpi, self.rate_ms = 1, 1, 1, 800, 1
		self.write_at = None
		self.outbox = []
		self.spying = False
		self.remap = bytes(range(1, 17))      # each button outputs its own HID button

	# transport interface
	def write(self, msg):
		index, feat, func_sw = msg[1:4]
		params = bytes(msg[4:])
		try:
			reply = self.handle(self.FEATURES[feat], func_sw >> 4, params)
			self.outbox.append(bytes([hidpp.LONG, index, feat, func_sw]) + bytes(reply).ljust(16, b'\0'))
		except (IndexError, KeyError):
			self.outbox.append(bytes([hidpp.LONG, index, 0xFF, feat, func_sw, 2]).ljust(20, b'\0'))

	def read(self, _timeout):
		return self.outbox.pop(0) if self.outbox else None

	def close(self):
		pass   # nothing to release: no file is open

	def sector(self, n):
		return self.memory.get(n, b'\xff' * SECTOR)

	def handle(self, feature, fn, p):
		handlers = {hidpp.ROOT: self._root, hidpp.FEATURE_SET: self._feature_set, hidpp.NAME: self._name,
		            hidpp.FIRMWARE: self._firmware, mouse.DPI: self._dpi, mouse.REPORT_RATE: self._rate,
		            features.UNIFIED_BATTERY: lambda _fn, _p: bytes([72, 4, 0, 0]), mouse.ONBOARD: self._onboard,
		            0x8110: self._spy}
		return handlers[feature](fn, p)

	def _spy(self, fn, p):
		"""0x8110 MouseButtonSpy as G HUB drives it: 0 count, 1 start, 2 stop, 3/4 get/set remap."""
		if fn == 0:
			return bytes([11])
		if fn in (1, 2):
			self.spying = fn == 1
			return b''
		if fn == 3:
			return self.remap
		self.remap = bytes(p[:16])
		return b''

	def press(self, mask):
		"""Simulate the buttons in mask being held (a 0x8110 event while spying)."""
		if self.spying:
			idx = self.FEATURES.index(0x8110)
			self.outbox.append(bytes([hidpp.LONG, 0xFF, idx, 0x00]) + struct.pack('>H', mask).ljust(16, b'\0'))

	def _root(self, fn, p):
		if fn == 0:
			fid = struct.unpack('>H', p[:2])[0]
			return bytes([self.FEATURES.index(fid) if fid in self.FEATURES else 0, 0, 0])
		return bytes([4, 2, p[2]])

	def _feature_set(self, fn, p):
		return bytes([len(self.FEATURES) - 1]) if fn == 0 else struct.pack('>HB', self.FEATURES[p[0]], 0)

	def _name(self, fn, p):
		answers = {0: lambda: bytes([len(self.device_name)]), 1: lambda: self.device_name[p[0]:p[0] + 16],
		           2: lambda: bytes([self.KIND])}
		return answers[fn]()

	@staticmethod
	def _firmware(fn, _p):
		return bytes([1]) if fn == 0 else b'\0U1 ' + bytes([0x12, 0x02, 0x00, 0x07])

	def _rate(self, fn, p):
		if fn == 0:
			return bytes([0b10001011])
		if fn == 1:
			return bytes([self.rate_ms])
		self.rate_ms = p[0]
		return b''

	def _dpi(self, fn, p):
		if fn == 0:
			return bytes([1])
		if fn == 1:
			return b'\0' + struct.pack('>HHHH', 100, 0xE000 | 50, 25600, 0)
		if fn == 2:
			return b'\0' + struct.pack('>HH', self.dpi, 800)
		self.dpi = struct.unpack('>H', p[1:3])[0]
		return b''

	def _onboard(self, fn, p):
		handlers = {
			0: lambda: bytes([1, 1, 1, 5, 3, 11, 16]) + struct.pack('>H', SECTOR) + bytes([2, 0]),
			1: lambda: self._set('mode', p[0]),
			2: lambda: bytes([self.mode]),
			3: lambda: self._set('profile', p[1]),
			4: lambda: bytes([0, self.profile]),
			5: lambda: self._read(p),
			6: lambda: self._set('write_at', (struct.unpack('>H', p[:2])[0], bytearray(), struct.unpack('>H', p[4:6])[0])),
			7: lambda: self._write(p),
			8: self._write_end,
			11: lambda: bytes([self.dpi_slot]),
			12: lambda: self._set('dpi_slot', p[0]),
		}
		return handlers[fn]()

	def _set(self, attr, value):
		setattr(self, attr, value)
		return b''

	def _read(self, p):
		sector, offset = struct.unpack('>HH', p[:4])
		if offset + 16 > SECTOR:
			raise KeyError(offset)
		return self.sector(sector)[offset:offset + 16]

	def _write(self, p):
		self.write_at[1].extend(p[:16])
		return b''

	def _write_end(self):
		sector, data, count = self.write_at
		self.memory[sector] = bytes(data[:count])
		self.write_at = None
		return b''


class FakeWheelMouse(FakeMouse):
	"""A mouse with SmartShift and ratchet force (0x2111), button swap (0x2005) and hybrid
	tracking (0x2400), like the G502 X."""
	FEATURES = ([f for f in FakeMouse.FEATURES if f not in (mouse.REPORT_RATE, mouse.DPI)]
	            + [0x2111, 0x2005, 0x2400, 0x8061, 0x2202, 0x80E0, 0x2240, 0x8103])

	def __init__(self):
		super().__init__('G502 X')
		self.wheel = [2, 10, 50]
		self.swap, self.hybrid = 0, 0
		self.rate_n = 3
		self.ext_dpi = (1600, 1600, 2)
		self.bhop = 0
		self.surface = None
		self.tags = {1: struct.pack('>H', 300), 2: struct.pack('>H', 600)}   # 5 and 10 minutes
		self.session = False
		self.pending = None
		self.tuning = []                        # surface tuning functions called, in order

	def handle(self, feature, fn, p):
		own = {0x2202: self._ext_dpi, 0x80E0: self._bunny_hop, 0x2240: self._surface_tuning,
		       0x8103: self._global_settings, 0x8061: self._rates, 0x2005: self._swap,
		       0x2400: self._hybrid, 0x2111: self._wheel}.get(feature)
		return own(fn, p) if own else super().handle(feature, fn, p)

	def _swap(self, fn, p):
		if fn == 1:
			self.swap = p[0]
		return bytes([self.swap])

	def _hybrid(self, fn, p):
		if fn == 3:
			self.hybrid = p[0]
		return bytes([1 if fn == 0 else self.hybrid])

	def _wheel(self, fn, p):
		if fn == 0:
			return bytes([1, 10, 50, 100])
		if fn == 1:
			return bytes(self.wheel)
		self.wheel = list(p[:3])
		return bytes(self.wheel)

	def _global_settings(self, fn, p):
		"""0x8103's tag protocol: sessions, tag reads and writes with a CRC-32 commit."""
		if fn == 5:
			self.session = p[0] == 0
			return bytes([0])
		if not self.session:
			raise KeyError('no session')
		if fn == 3:
			tag = struct.unpack('>H', p[:2])[0]
			self.reading = self.tags[tag]
			return bytes([7]) + struct.pack('>H', len(self.reading))
		if fn == 4:
			chunk, self.reading = self.reading[:15], self.reading[15:]
			return bytes([p[0]]) + chunk
		if fn == 6:
			tag, size = struct.unpack('>HH', p[:4])
			self.pending = (tag, size, bytearray(p[4:4 + min(size, 12)]))
			return bytes([9])
		if fn == 7:
			self.pending[2].extend(p[1:16])
			return bytes([p[0]])
		tag, size, data = self.pending
		data = bytes(data[:size])
		ok = struct.unpack('>I', p[:4])[0] == zlib.crc32(data)
		if ok:
			self.tags[tag] = data
		return bytes([0 if ok else 1, 0, 0])

	def _surface_tuning(self, fn, p):
		self.tuning.append(fn)
		idx = self.FEATURES.index(0x2240)
		if fn == 0:                             # [?, ?, ?, in use (3), factory (3)]
			return bytes([0, 0, 0] + (self.surface or [20, 5, 25]) + [20, 5, 25])
		if fn == 1:
			self.surface = list(p[:3])
		elif fn == 3:                           # shutter calibrated: done, LED drive 42
			self.outbox.append(bytes([hidpp.LONG, 0xFF, idx, 0x00, 0, 42]).ljust(20, b'\0'))
		elif fn == 5:                           # squal calibrated: done, threshold 7, min squal 30
			self.outbox.append(bytes([hidpp.LONG, 0xFF, idx, 0x10, 0, 7, 30]).ljust(20, b'\0'))
		return b''

	def _bunny_hop(self, fn, p):
		if fn == 2:
			self.bhop = p[0]
		return bytes([self.bhop])

	def _rates(self, fn, p):
		if fn == 1:
			return bytes([0, 0x7F])                 # 125 Hz to 8 kHz
		if fn == 2:
			return bytes([self.rate_n])
		if fn == 3:
			self.rate_n = p[0]
		return b''

	def _ext_dpi(self, fn, p):
		if fn == 1:
			return bytes([0, 0, 0b11])
		if fn == 2:                             # 100 to 32000 in steps of 50, one page
			return bytes([0, 0, p[2]]) + struct.pack('>HHHH', 100, 0xE032, 32000, 0) if p[2] == 0 else bytes(16)
		if fn == 5:
			x, y, lod = self.ext_dpi
			return b'\0' + struct.pack('>HHHH', x, 800, y, 800) + bytes([lod])
		if fn == 6:
			x, y = struct.unpack('>HH', p[1:5])
			self.ext_dpi = (x, y, p[5])
			return bytes([0])
		return b''


class FakeKeyboard(FakeMouse):
	"""A corded G815-like keyboard: two lighting zones, brightness, report rate, onboard mode."""
	FEATURES = [hidpp.ROOT, hidpp.FEATURE_SET, hidpp.FIRMWARE, hidpp.NAME, features.COLOR_LED_EFFECTS,
	            features.BRIGHTNESS, mouse.REPORT_RATE, mouse.ONBOARD, 0x8010, 0x8020, 0x4522, 0x8081, 0x40A3]
	ZONE_EFFECTS = [features.FIXED, features.BREATHING, features.CYCLE, 0x0008, 0x0000]
	KIND = 0   # keyboard

	def __init__(self):
		super().__init__('G815 RGB MECHANICAL GAMING KEYBOARD')
		self.effects = {0: (0, b''), 1: (1, b'')}
		self.level = 80
		self.keys = {}       # 0x8081 zone -> (r, g, b), shown after a frame end
		self.pending = {}
		self.persisted = None
		self.disabled = set()
		self.fn_inverted = False
		self.gkeys_software = False
		self.m_led = 0

	def handle(self, feature, fn, p):
		handlers = {features.COLOR_LED_EFFECTS: self._lighting, features.DISABLE_KEYS: self._disable_keys,
		            0x8010: self._gkeys, 0x8020: self._mkeys, features.FN_INVERSION: self._fn_keys,
		            features.CHANGE_HOST: lambda f, _p: bytes([3, 1, 0]) if f == 0 else b'',
		            0x8081: self._perkey, features.BRIGHTNESS: self._brightness}
		if feature in handlers:
			return handlers[feature](fn, p)
		return super().handle(feature, fn, p)

	def _gkeys(self, fn, p):           # fn 2 = software control
		if fn == 2:
			self.gkeys_software = bool(p[0])
		return bytes([5])

	def _mkeys(self, fn, p):           # fn 0 count, fn 1 lit key
		if fn == 1:
			self.m_led = p[0]
		return bytes([3])

	def _fn_keys(self, fn, p):
		if fn == 1:
			self.fn_inverted = bool(p[1])
		return bytes([p[0], self.fn_inverted, 1, 1])

	def _lighting(self, fn, p):
		if fn == 0:
			return bytes([2])
		if fn == 1:
			return bytes([p[0]]) + struct.pack('>H', 1 if p[0] == 0 else 2) + bytes([len(self.ZONE_EFFECTS)])
		if fn == 2:
			return bytes([p[0], p[1]]) + struct.pack('>H', self.ZONE_EFFECTS[p[1]])
		self.effects[p[0]] = (p[1], bytes(p[2:12]))
		return b''

	def event(self, feature, payload):
		"""A notification (event 0) from one of the keyboard's features."""
		idx = self.FEATURES.index(feature)
		self.outbox.append(bytes([hidpp.LONG, 0xFF, idx, 0x00]) + bytes(payload).ljust(16, b'\0'))

	def _disable_keys(self, fn, p):
		if fn == 0:
			return bytes([8])
		if fn == 1:
			self.disabled |= {u for u in p if u}
		elif fn == 2:
			self.disabled -= set(p)
		elif fn == 3:
			self.disabled = set()
		return b''

	def _perkey(self, fn, p):
		if fn == 1:   # SetIndividualRgbZones: up to 4 x (zone, r, g, b), echoed back
			for i in range(0, 16, 4):
				if p[i]:
					self.pending[p[i]] = tuple(p[i + 1:i + 4])
			return bytes(p[:16])
		if fn == 6:   # SetRgbZonesSingleValue: r, g, b, then zone ids
			for zone in p[3:16]:
				if zone:
					self.pending[zone] = tuple(p[:3])
			self.calls = getattr(self, 'calls', 0) + 1
			return b''
		if fn == 7:   # FrameEnd
			self.keys.update(self.pending)
			self.pending = {}
			self.persisted = bool(p[0])
		return b''

	def _brightness(self, fn, p):
		if fn == 0:
			return struct.pack('>HB', 100, 10)
		if fn == 1:
			return struct.pack('>H', self.level)
		self.level = struct.unpack('>H', p[:2])[0]
		return b''


class FakeMultiHostKeyboard(FakeKeyboard):
	"""A G915-like wireless keyboard with Easy-Switch (0x1814) and host names (0x1815), on its
	second of three hosts."""
	FEATURES = FakeKeyboard.FEATURES + [0x1814, 0x1815]
	NAMES = (b'desktop', b'my-laptop-running-linux', b'')

	def handle(self, feature, fn, p):
		if feature != 0x1815:
			return super().handle(feature, fn, p)
		name = self.NAMES[p[0]]
		if fn == 1:
			return bytes([p[0], 1, 1, 1, len(name), 24])
		return bytes([p[0], p[1]]) + name[p[1]:p[1] + 14]


class FakeAnalogKeyboard(FakeKeyboard):
	"""A PRO X TKL RAPID-like keyboard: analog keys' switches (0x1B08)."""
	FEATURES = FakeKeyboard.FEATURES + [features.ANALOG_KEYS]

	def __init__(self):
		super().__init__()
		self.analog = {1: 0, 4: 0}      # get fn -> bit 0

	def handle(self, feature, fn, p):
		if feature != features.ANALOG_KEYS:
			return super().handle(feature, fn, p)
		if fn in (2, 5):
			self.analog[fn - 1] = p[0] & 1
		return bytes([self.analog.get(fn, 0)])


class FakeKeyboardV1(FakeKeyboard):
	"""A G810-like keyboard: per-key lighting over 0x8080 (keyboard keys, media keys, logo)."""
	FEATURES = [hidpp.ROOT, hidpp.FEATURE_SET, hidpp.FIRMWARE, hidpp.NAME, 0x8080, 0x4521]

	def __init__(self):
		super().__init__()
		self.keys, self.pending, self.persisted = {}, {}, None
		self.disabled = 0

	def handle(self, feature, fn, p):
		if feature == 0x4521:                   # Caps Lock, Scroll Lock, Windows
			if fn == 2:
				self.disabled = p[0]
			return bytes([0x15 if fn == 0 else self.disabled])
		if feature != 0x8080:
			return super().handle(feature, fn, p)
		if fn == 0:
			return struct.pack('>H', 0x13)         # keyboard, consumer, logo
		if fn == 3:
			kind, count = struct.unpack('>HH', p[:4])
			for i in range(count):
				key, r, g, b = p[4 + 4 * i:8 + 4 * i]
				self.pending[(kind, key)] = (r, g, b)
			return b''
		if fn == 5:
			self.keys.update(self.pending)
			self.pending = {}
			self.persisted = bool(p[0])
		return b''


class FakeEqHeadset(FakeMouse):
	"""A headset with its own equalizer (0x8310): five bands, -12 to +12 dB."""
	FEATURES = [hidpp.ROOT, hidpp.FEATURE_SET, hidpp.FIRMWARE, hidpp.NAME, 0x8310, 0x8305]
	FREQS = (80, 240, 750, 2200, 6600)

	def __init__(self):
		super().__init__('G935 Gaming Headset')
		self.gains, self.eq_on, self.lead = [0] * 5, True, None
		self.bass = 50

	def handle(self, feature, fn, p):
		if feature == 0x8305:
			if fn == 1:
				self.bass = p[0]
			return bytes([self.bass])
		if feature != 0x8310:
			return super().handle(feature, fn, p)
		if fn == 0:
			return bytes([5, 24, 0]) + struct.pack('bb', -12, 12)
		if fn == 1:
			rest = self.FREQS[p[0]:p[0] + 7]
			return bytes([p[0]]) + b''.join(struct.pack('>H', f) for f in rest)
		if fn == 2:
			return struct.pack('5b', *self.gains)
		if fn == 3:
			self.lead, self.gains = p[0], list(struct.unpack('5b', p[1:6]))
			return b''
		if fn == 4:
			return bytes([self.eq_on])
		self.eq_on = bool(p[0])
		return b''


class FakeRgbMouse(FakeMouse):
	"""A newer mouse with 0x8071 RGB effects: two clusters (primary, logo), three effects each."""
	FEATURES = [hidpp.ROOT, hidpp.FEATURE_SET, hidpp.FIRMWARE, hidpp.NAME, 0x8071]
	EFFECTS = (features.FIXED, features.BREATHING, features.CYCLE)

	def __init__(self):
		super().__init__('G502 X PLUS')
		self.set = {}

	def handle(self, feature, fn, p):
		if feature != 0x8071:
			return super().handle(feature, fn, p)
		if fn == 0:
			if p[0] == 0xFF:
				return bytes([0xFF, 0xFF, 2])
			if p[1] == 0xFF:
				return bytes([p[0], 0xFF]) + struct.pack('>H', 1 if p[0] == 0 else 2) + bytes([3])
			return bytes([p[0], p[1]]) + struct.pack('>H', self.EFFECTS[p[1]])
		self.set[p[0]] = (p[1], bytes(p[2:12]), p[12])
		return b''


class FakeYeti(FakeMouse):
	"""A Yeti X-like microphone: polar pattern (0x8330), all four patterns."""
	FEATURES = [hidpp.ROOT, hidpp.FEATURE_SET, hidpp.FIRMWARE, hidpp.NAME, features.POLAR_PATTERN,
	            features.MIC_GAIN_ADJUST, features.HEADPHONE_ADJUST, features.MIC_BLEND, features.JACK_DETECTION]
	KIND = 8

	def __init__(self):
		super().__init__('Yeti X')
		self.pattern = 2
		self.mic = {0: 1, 2: 60}          # type -> value: mic on, gain 60
		self.phones = {0: 1, 2: 40}       # headphones on, level 40
		self.monitor = 30

	def handle(self, feature, fn, p):
		if feature == features.MIC_GAIN_ADJUST:
			return self._gain_adjust(fn, p, self.mic)
		if feature == features.HEADPHONE_ADJUST:
			return self._gain_adjust(fn, p, self.phones)
		if feature == features.JACK_DETECTION:
			return bytes([1, 1])                # headphones in
		if feature == features.MIC_BLEND:
			if fn == 2:
				self.monitor = p[2]
			return bytes([1]) if fn == 0 else bytes([p[0], p[1], 1, self.monitor])
		if feature == features.POLAR_PATTERN:
			if fn == 0:
				return bytes([0x0F])
			if fn == 1:
				return bytes([self.pattern])
			self.pattern = p[0]
			return bytes([self.pattern])
		return super().handle(feature, fn, p)


	@staticmethod
	def _gain_adjust(fn, p, controls):
		if fn == 0:
			return bytes([1])
		if fn == 1:
			return bytes([0, 2])
		if fn == 2:
			kind = (0, 2)[p[1]]
			return bytes([0, p[1], kind, controls[kind]])
		controls[p[1]] = p[2]
		return bytes(p[:3])


class FakeReceiver:
	"""A LIGHTSPEED receiver with one wireless G502 in slot 1; empty slots answer like a
	receiver does (HID++ 1.0 error)."""

	def __init__(self):
		self.slots = {1: FakeMouse('G502 LIGHTSPEED Wireless Gaming Mouse')}
		self.outbox = []

	def write(self, msg):
		slot = self.slots.get(msg[1])
		if slot:
			slot.write(msg)
			self.outbox.extend(slot.outbox)
			slot.outbox.clear()
		else:
			self.outbox.append(bytes([hidpp.SHORT, msg[1], 0x8F, msg[2], msg[3], 0x08, 0]))

	def read(self, _timeout):
		return self.outbox.pop(0) if self.outbox else None

	def close(self):
		pass   # nothing to release: no file is open


MICE = ('c08b', 'c08d', 'c332', 'c07d', 'c084', 'c092')
KEYBOARDS = ('c33f', 'c339', 'c33c', 'c343', 'c33e')
ANALOG_KEYBOARDS = ('c35b',)     # PRO X TKL RAPID
YETIS = ('0aaf',)
RECEIVERS = ('c539', 'c53a', 'c53f', 'c541', 'c545', 'c547', 'c548', 'c52b')
_FAKES = {}


def transport_for(usb_id, port):
	"""A simulated HID++ interface for a faked USB device, or None. One per port, kept for the
	app's lifetime so changes stick while it runs."""
	pid = usb_id.split(':')[1]
	kinds = {**dict.fromkeys(MICE, FakeMouse), **dict.fromkeys(KEYBOARDS, FakeKeyboard),
	         **dict.fromkeys(ANALOG_KEYBOARDS, FakeAnalogKeyboard),
	         **dict.fromkeys(YETIS, FakeYeti),
	         **dict.fromkeys(RECEIVERS, FakeReceiver)}
	if pid not in kinds:
		return None
	if port not in _FAKES:
		_FAKES[port] = kinds[pid]()
	return _FAKES[port]
