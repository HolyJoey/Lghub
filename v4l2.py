"""Webcam controls through the standard Linux video interface (V4L2), with plain ioctls.

Lists a camera's controls (brightness, focus, zoom, ...), reads and sets them. Works for any
UVC webcam; the C920 and other Logitech cameras need nothing special.
"""
import fcntl
import os
import re
import struct

# struct layouts from linux/videodev2.h
_QUERYCTRL = struct.Struct('=II32siiiiI8x')       # id, type, name, min, max, step, default, flags
_QUERYMENU = struct.Struct('=II32sI')             # id, index, name (or s64 value), reserved
_CONTROL = struct.Struct('=Ii')                   # id, value


def _iowr(nr, size):
	return (3 << 30) | (size << 16) | (ord('V') << 8) | nr


VIDIOC_G_CTRL = _iowr(27, _CONTROL.size)
VIDIOC_S_CTRL = _iowr(28, _CONTROL.size)
VIDIOC_QUERYCTRL = _iowr(36, _QUERYCTRL.size)
VIDIOC_QUERYMENU = _iowr(37, _QUERYMENU.size)

NEXT_CTRL = 0x80000000
FLAG_DISABLED, FLAG_READ_ONLY, FLAG_INACTIVE, FLAG_WRITE_ONLY = 0x01, 0x04, 0x10, 0x40
T_INTEGER, T_BOOLEAN, T_MENU, T_BUTTON, T_CLASS, T_INTEGER_MENU = 1, 2, 3, 4, 6, 9

SYS_VIDEO = '/sys/class/video4linux'


class Control:
	def __init__(self, cid, kind, name, low, high, step, default, flags):
		self.id = cid
		self.kind = kind
		self.name = name
		self.low, self.high, self.step, self.default = low, high, max(1, step), default
		self.flags = flags
		self.value = default
		self.menu = {}             # value -> label, for menus

	@property
	def key(self):
		"""A stable name for saving: lower-case, underscores."""
		return re.sub(r'[^a-z0-9]+', '_', self.name.lower()).strip('_')

	@property
	def inactive(self):
		return bool(self.flags & FLAG_INACTIVE)

	@property
	def read_only(self):
		return bool(self.flags & FLAG_READ_ONLY)


class Camera:
	def __init__(self, path):
		self.path = path
		self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

	def close(self):
		try:
			os.close(self.fd)
		except OSError:
			pass

	def controls(self):
		"""Every usable control, in the driver's order, with current values."""
		found = []
		cid = NEXT_CTRL
		while True:
			buf = bytearray(_QUERYCTRL.pack(cid, 0, b'', 0, 0, 0, 0, 0))
			try:
				fcntl.ioctl(self.fd, VIDIOC_QUERYCTRL, buf)
			except OSError:
				break
			qid, kind, name, low, high, step, default, flags = _QUERYCTRL.unpack(buf)
			cid = qid | NEXT_CTRL
			if flags & FLAG_DISABLED or kind not in (T_INTEGER, T_BOOLEAN, T_MENU, T_INTEGER_MENU):
				continue
			ctrl = Control(qid, kind, name.split(b'\0')[0].decode('utf-8', 'replace'), low, high, step, default, flags)
			if kind in (T_MENU, T_INTEGER_MENU):
				ctrl.menu = self._menu(ctrl)
			if not flags & FLAG_WRITE_ONLY:
				try:
					ctrl.value = self.get(qid)
				except OSError:
					pass
			found.append(ctrl)
		return found

	def _menu(self, ctrl):
		items = {}
		for index in range(ctrl.low, ctrl.high + 1):
			buf = bytearray(_QUERYMENU.pack(ctrl.id, index, b'', 0))
			try:
				fcntl.ioctl(self.fd, VIDIOC_QUERYMENU, buf)
			except OSError:
				continue
			raw = bytes(buf[8:40])
			if ctrl.kind == T_INTEGER_MENU:
				items[index] = str(struct.unpack('=q', raw[:8])[0])
			else:
				items[index] = raw.split(b'\0')[0].decode('utf-8', 'replace')
		return items

	def get(self, cid):
		buf = bytearray(_CONTROL.pack(cid, 0))
		fcntl.ioctl(self.fd, VIDIOC_G_CTRL, buf)
		return _CONTROL.unpack(buf)[1]

	def set(self, cid, value):
		fcntl.ioctl(self.fd, VIDIOC_S_CTRL, bytearray(_CONTROL.pack(cid, int(value))))


def video_node(usb_port):
	"""/dev/videoN of a USB camera's main capture node (port like '3-2'), or None."""
	try:
		names = sorted(os.listdir(SYS_VIDEO), key=lambda n: int(''.join(filter(str.isdigit, n)) or 0))
	except OSError:
		return None
	for name in names:
		real = os.path.realpath(os.path.join(SYS_VIDEO, name, 'device'))
		if f'/{usb_port}:' not in real:
			continue
		try:
			with open(os.path.join(SYS_VIDEO, name, 'index')) as f:
				if f.read().strip() != '0':
					continue
		except OSError:
			pass
		return f'/dev/{name}'
	return None
