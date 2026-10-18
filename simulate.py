"""Pretend HID++ devices, for trying pages without the hardware (LGHUB_FAKE_DEVICES) and for
the tests. They follow the protocol as hidpp.py and mouse.py use it; they are not a record of
any real device's answers."""
import struct

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


class FakeKeyboard(FakeMouse):
	"""A corded G815-like keyboard: two lighting zones, brightness, report rate, onboard mode."""
	FEATURES = [hidpp.ROOT, hidpp.FEATURE_SET, hidpp.FIRMWARE, hidpp.NAME, features.COLOR_LED_EFFECTS,
	            features.BRIGHTNESS, mouse.REPORT_RATE, mouse.ONBOARD, 0x8010, 0x8020, 0x4522]
	ZONE_EFFECTS = [features.FIXED, features.BREATHING, features.CYCLE, 0x0008, 0x0000]
	KIND = 0   # keyboard

	def __init__(self):
		super().__init__('G815 RGB MECHANICAL GAMING KEYBOARD')
		self.effects = {0: (0, b''), 1: (1, b'')}
		self.level = 80

	def handle(self, feature, fn, p):
		if feature == features.COLOR_LED_EFFECTS:
			return self._lighting(fn, p)
		if feature == features.BRIGHTNESS:
			return self._brightness(fn, p)
		return super().handle(feature, fn, p)

	def _lighting(self, fn, p):
		if fn == 0:
			return bytes([2])
		if fn == 1:
			return bytes([p[0]]) + struct.pack('>H', 1 if p[0] == 0 else 2) + bytes([len(self.ZONE_EFFECTS)])
		if fn == 2:
			return bytes([p[0], p[1]]) + struct.pack('>H', self.ZONE_EFFECTS[p[1]])
		self.effects[p[0]] = (p[1], bytes(p[2:12]))
		return b''

	def _brightness(self, fn, p):
		if fn == 0:
			return struct.pack('>HB', 100, 10)
		if fn == 1:
			return struct.pack('>H', self.level)
		self.level = struct.unpack('>H', p[:2])[0]
		return b''


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
RECEIVERS = ('c539', 'c53a', 'c53f', 'c541', 'c545', 'c547', 'c548', 'c52b')
_FAKES = {}


def transport_for(usb_id, port):
	"""A simulated HID++ interface for a faked USB device, or None. One per port, kept for the
	app's lifetime so changes stick while it runs."""
	pid = usb_id.split(':')[1]
	kinds = {**dict.fromkeys(MICE, FakeMouse), **dict.fromkeys(KEYBOARDS, FakeKeyboard),
	         **dict.fromkeys(RECEIVERS, FakeReceiver)}
	if pid not in kinds:
		return None
	if port not in _FAKES:
		_FAKES[port] = kinds[pid]()
	return _FAKES[port]
