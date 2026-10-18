"""A virtual keyboard and mouse through /dev/uinput, for macros and remapped buttons.

Macros are stored the way G HUB stores them: keys as USB HID usages. KEYBOARD and CONSUMER
map those to Linux key codes (values from linux/input-event-codes.h).
"""
import fcntl
import os
import struct
import time

EV_SYN, EV_KEY, EV_REL = 0, 1, 2
SYN_REPORT = 0
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0, 1, 6, 8
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA = 272, 273, 274, 275, 276
KEY_MAX = 767

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_DEV_SETUP = 0x405c5503
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
BUS_VIRTUAL = 0x06
_EVENT = struct.Struct('llHHi')

# HID keyboard usage (page 7) -> Linux key code
KEYBOARD = {0x04: 30, 0x05: 48, 0x06: 46, 0x07: 32, 0x08: 18, 0x09: 33, 0x0a: 34, 0x0b: 35, 0x0c: 23, 0x0d: 36,
            0x0e: 37, 0x0f: 38, 0x10: 50, 0x11: 49, 0x12: 24, 0x13: 25, 0x14: 16, 0x15: 19, 0x16: 31, 0x17: 20,
            0x18: 22, 0x19: 47, 0x1a: 17, 0x1b: 45, 0x1c: 21, 0x1d: 44, 0x1e: 2, 0x1f: 3, 0x20: 4, 0x21: 5,
            0x22: 6, 0x23: 7, 0x24: 8, 0x25: 9, 0x26: 10, 0x27: 11, 0x28: 28, 0x29: 1, 0x2a: 14, 0x2b: 15,
            0x2c: 57, 0x2d: 12, 0x2e: 13, 0x2f: 26, 0x30: 27, 0x31: 43, 0x32: 43, 0x33: 39, 0x34: 40, 0x35: 41,
            0x36: 51, 0x37: 52, 0x38: 53, 0x39: 58, 0x3a: 59, 0x3b: 60, 0x3c: 61, 0x3d: 62, 0x3e: 63, 0x3f: 64,
            0x40: 65, 0x41: 66, 0x42: 67, 0x43: 68, 0x44: 87, 0x45: 88, 0x46: 99, 0x47: 70, 0x48: 119, 0x49: 110,
            0x4a: 102, 0x4b: 104, 0x4c: 111, 0x4d: 107, 0x4e: 109, 0x4f: 106, 0x50: 105, 0x51: 108, 0x52: 103,
            0x53: 69, 0x54: 98, 0x55: 55, 0x56: 74, 0x57: 78, 0x58: 96, 0x59: 79, 0x5a: 80, 0x5b: 81, 0x5c: 75,
            0x5d: 76, 0x5e: 77, 0x5f: 71, 0x60: 72, 0x61: 73, 0x62: 82, 0x63: 83, 0x64: 86, 0x65: 127, 0x66: 116,
            0x67: 117, 0x68: 183, 0x69: 184, 0x6a: 185, 0x6b: 186, 0x6c: 187, 0x6d: 188, 0x6e: 189, 0x6f: 190,
            0x70: 191, 0x71: 192, 0x72: 193, 0x73: 194, 0xe0: 29, 0xe1: 42, 0xe2: 56, 0xe3: 125, 0xe4: 97,
            0xe5: 54, 0xe6: 100, 0xe7: 126}
# HID consumer usage (page 12, media keys) -> Linux key code
CONSUMER = {0x06f: 225, 0x070: 224, 0x0b5: 163, 0x0b6: 165, 0x0b7: 166, 0x0cd: 164, 0x0e2: 113, 0x0e9: 115,
            0x0ea: 114, 0x183: 171, 0x18a: 155, 0x192: 140, 0x194: 144, 0x221: 217, 0x223: 172, 0x224: 158,
            0x225: 159, 0x227: 173}
# HID button number (1-based, as in G HUB's Mouse macro) -> Linux button
BUTTONS = {1: BTN_LEFT, 2: BTN_RIGHT, 3: BTN_MIDDLE, 4: BTN_SIDE, 5: BTN_EXTRA}
MODIFIER_USAGES = {0xe0: 'Ctrl', 0xe1: 'Shift', 0xe2: 'Alt', 0xe3: 'Super', 0xe4: 'Right Ctrl', 0xe5: 'Right Shift',
                   0xe6: 'AltGr', 0xe7: 'Right Super'}


class VirtualInput:
	"""Created once; raises OSError when /dev/uinput isn't accessible."""

	def __init__(self, name='Lghub virtual input'):
		self.fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
		try:
			fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
			fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
			for code in set(KEYBOARD.values()) | set(CONSUMER.values()) | set(BUTTONS.values()):
				fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
			for rel in (REL_X, REL_Y, REL_WHEEL, REL_HWHEEL):
				fcntl.ioctl(self.fd, UI_SET_RELBIT, rel)
			setup = struct.pack('HHHH80sI', BUS_VIRTUAL, 0x046d, 0x0001, 1, name.encode()[:79], 0)
			fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
			fcntl.ioctl(self.fd, UI_DEV_CREATE)
		except OSError:
			os.close(self.fd)
			raise
		time.sleep(0.05)   # let the desktop pick up the new device before the first event

	def close(self):
		try:
			fcntl.ioctl(self.fd, UI_DEV_DESTROY)
		finally:
			os.close(self.fd)

	def _emit(self, typ, code, value):
		os.write(self.fd, _EVENT.pack(0, 0, typ, code, value))

	def sync(self):
		self._emit(EV_SYN, SYN_REPORT, 0)

	def key(self, code, down):
		self._emit(EV_KEY, code, 1 if down else 0)
		self.sync()

	def usage(self, usage, down, consumer=False):
		"""Press or release a key given as a HID usage. False if there's no Linux key for it."""
		code = (CONSUMER if consumer else KEYBOARD).get(usage)
		if code is None:
			return False
		self.key(code, down)
		return True

	def tap(self, code):
		self.key(code, True)
		self.key(code, False)

	def wheel(self, clicks, horizontal=False):
		self._emit(EV_REL, REL_HWHEEL if horizontal else REL_WHEEL, clicks)
		self.sync()
