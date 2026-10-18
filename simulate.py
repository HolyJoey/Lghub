"""Pretend HID++ devices, for trying pages without the hardware (LGHUB_FAKE_DEVICES) and for
the tests. They follow the protocol as hidpp.py and mouse.py use it; they are not a record of
any real device's answers."""
import struct

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
	            mouse.REPORT_RATE, mouse.ONBOARD]

	def __init__(self, name='G502 HERO Gaming Mouse'):
		self.device_name = name.encode()
		self.memory = {mouse.ROM | 1: _profile(1, [400, 800, 1600, 3200, 6400], (0, 140, 255)),
		               mouse.ROM | 2: _profile(2, [1200, 2400], (255, 60, 0)),
		               mouse.ROM | 3: _profile(3, [800], (60, 255, 120))}
		self.mode, self.profile, self.dpi_slot, self.dpi, self.rate_ms = 1, 1, 1, 800, 1
		self.write_at = None
		self.outbox = []

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
		pass

	def sector(self, n):
		return self.memory.get(n, b'\xff' * SECTOR)

	def handle(self, feature, fn, p):
		if feature == hidpp.ROOT:
			if fn == 0:
				fid = struct.unpack('>H', p[:2])[0]
				return bytes([self.FEATURES.index(fid) if fid in self.FEATURES else 0, 0, 0])
			return bytes([4, 2, p[2]])
		if feature == hidpp.FEATURE_SET:
			if fn == 0:
				return bytes([len(self.FEATURES) - 1])
			return struct.pack('>HB', self.FEATURES[p[0]], 0)
		if feature == hidpp.NAME:
			if fn == 0:
				return bytes([len(self.device_name)])
			if fn == 1:
				return self.device_name[p[0]:p[0] + 16]
			return bytes([3])
		if feature == hidpp.FIRMWARE:
			if fn == 0:
				return bytes([1])
			return b'\0U1 ' + bytes([0x12, 0x02, 0x00, 0x07])
		if feature == mouse.DPI:
			return self._dpi(fn, p)
		if feature == mouse.REPORT_RATE:
			if fn == 0:
				return bytes([0b10001011])
			if fn == 1:
				return bytes([self.rate_ms])
			self.rate_ms = p[0]
			return b''
		return self._onboard(fn, p)

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


_FAKES = {}


def device_for(usb_id, port):
	"""A simulated hidpp.Device for a faked USB device, or None. One per port, kept for the
	app's lifetime so changes stick while it runs."""
	if usb_id.split(':')[1] not in ('c08b', 'c08d', 'c332', 'c07d', 'c084', 'c092'):
		return None
	if port not in _FAKES:
		_FAKES[port] = hidpp.Device(FakeMouse())
	return _FAKES[port]
