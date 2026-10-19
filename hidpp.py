"""Logitech HID++ 2.0 over hidraw: ask a device which features it has, then call them.

A request is a long report: [0x11, device index, feature index, function << 4 | sw id, params].
The device answers with the same header, or with an error report (feature index 0xFF for
HID++ 2.0, sub id 0x8F for HID++ 1.0). Index 0xFF addresses a corded device directly; 1-6
address devices paired to a receiver.

Feature ids used here (see the per-device modules for what they do):
	0x0000 root, 0x0001 feature set, 0x0003 firmware, 0x0005 name and type.
"""
import errno
import os
import select
import struct
import threading
import time

SHORT, LONG, VERY_LONG = 0x10, 0x11, 0x12
SIZES = {SHORT: 7, LONG: 20, VERY_LONG: 64}
CORDED = 0xFF
BACKLOG = 64            # notifications kept while a request waits (nobody may be listening)
SW_ID = 0x0A           # ours; notifications from the device carry 0
TIMEOUT = 1.0

ROOT = 0x0000
FEATURE_SET = 0x0001
FIRMWARE = 0x0003
NAME = 0x0005

ERRORS = {
	1: 'unknown', 2: 'invalid argument', 3: 'out of range', 4: 'hardware error',
	5: 'logitech internal', 6: 'invalid feature index', 7: 'invalid function', 8: 'busy',
	9: 'unsupported',
}

# Device kinds reported by feature 0x0005, function 2.
KINDS = {0: 'keyboard', 1: 'remote', 2: 'numpad', 3: 'mouse', 4: 'touchpad', 5: 'trackball',
         6: 'presenter', 7: 'receiver', 8: 'headset', 9: 'webcam', 10: 'steering wheel',
         11: 'joystick', 12: 'gamepad', 13: 'dock', 14: 'speaker', 15: 'microphone'}


class HidppError(Exception):
	def __init__(self, code, feature=None, function=None):
		self.code = code
		where = f' (feature 0x{feature:04x}, function {function})' if feature is not None else ''
		super().__init__(f'device error: {ERRORS.get(code, code)}{where}')


class NoReply(HidppError):
	def __init__(self):
		Exception.__init__(self, 'the device did not answer')
		self.code = None


class HidrawTransport:
	"""One /dev/hidrawN. Reads skip reports that aren't the answer we wait for."""

	def __init__(self, path):
		self.path = path
		self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
		self.lock = threading.Lock()   # shared by every Device on this interface

	def write(self, data):
		os.write(self.fd, bytes(data))

	def read(self, timeout):
		ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
		if not ready:
			return None
		try:
			return os.read(self.fd, 64)
		except BlockingIOError:
			return None

	def close(self):
		try:
			os.close(self.fd)
		except OSError:
			pass


class Device:
	"""A HID++ 2.0 device behind a transport. Thread-safe: requests on one interface are
	serialised, also between the devices paired to one receiver."""

	def __init__(self, transport, index=CORDED, reports=(LONG,)):
		self.transport = transport
		self.index = index
		self.reports = set(reports) or {LONG}
		self._features = {ROOT: 0}
		self._backlog = []      # notifications that came in while waiting for an answer
		if not hasattr(transport, 'lock'):
			transport.lock = threading.Lock()

	def close(self):
		self.transport.close()

	def request(self, feature_index, function, params=b''):
		"""Send one request and return the 16 parameter bytes of the answer."""
		func_sw = (function << 4) | SW_ID
		report = self._report_for(len(params))
		msg = bytes([report, self.index, feature_index, func_sw]) + bytes(params)
		msg = msg.ljust(SIZES[report], b'\0')[:SIZES[report]]
		with self.transport.lock:
			self.transport.write(msg)
			deadline = time.monotonic() + TIMEOUT
			while (left := deadline - time.monotonic()) > 0:
				reply = self.transport.read(left)
				if not reply or len(reply) < 5 or reply[0] not in SIZES or reply[1] != self.index:
					continue
				if reply[2] not in (0xFF, 0x8F) and not reply[3] & 0x0F:
					if len(self._backlog) < BACKLOG:
						self._backlog.append(reply)    # a notification: next_event gets it
					continue
				if reply[2] in (0xFF, 0x8F) and reply[3] == feature_index and reply[4] == func_sw:
					raise HidppError(reply[5] if len(reply) > 5 else 0)
				if reply[2] == feature_index and reply[3] == func_sw:
					return bytes(reply[4:]).ljust(16, b'\0')
		raise NoReply()

	def _report_for(self, size):
		"""The smallest report the device takes that fits size parameter bytes."""
		if SHORT in self.reports and size <= SIZES[SHORT] - 4:
			return SHORT
		if size > SIZES[LONG] - 4 and VERY_LONG in self.reports:
			return VERY_LONG
		return LONG

	def next_event(self, timeout):
		"""(feature index, event number, 16 parameter bytes) of the next notification from the
		device (software id 0), or None after timeout seconds. Use from one thread at a time."""
		deadline = time.monotonic() + timeout
		while (left := deadline - time.monotonic()) > 0:
			with self.transport.lock:
				report = self._backlog.pop(0) if self._backlog else self.transport.read(left)
			if not report or len(report) < 4 or report[0] not in SIZES or report[1] != self.index:
				continue
			if report[2] in (0xFF, 0x8F) or report[3] & 0x0F:
				continue   # an error or an answer to a request, not a notification
			return report[2], report[3] >> 4, bytes(report[4:]).ljust(16, b'\0')
		return None

	def feature_index(self, feature_id):
		"""The device's index for a feature, or None if it doesn't have it (cached)."""
		if feature_id not in self._features:
			reply = self.request(0, 0, struct.pack('>H', feature_id))
			self._features[feature_id] = reply[0] or None
		return self._features[feature_id]

	def has(self, feature_id):
		return self.feature_index(feature_id) is not None

	def call(self, feature_id, function, params=b''):
		index = self.feature_index(feature_id)
		if index is None:
			raise HidppError(6, feature_id, function)
		try:
			return self.request(index, function, params)
		except NoReply:
			raise
		except HidppError as e:
			raise HidppError(e.code, feature_id, function) from None

	# --- what every device answers --------------------------------------------------------

	def protocol_version(self):
		"""(major, minor); raises NoReply when nothing is there."""
		reply = self.request(0, 1, b'\0\0\x5a')
		return reply[0], reply[1]

	def feature_list(self):
		"""{feature id: index} for everything the device has."""
		if not self.has(FEATURE_SET):
			return dict(self._features)
		count = self.call(FEATURE_SET, 0)[0]
		for i in range(1, count + 1):
			fid = struct.unpack('>H', self.call(FEATURE_SET, 1, bytes([i]))[:2])[0]
			self._features[fid] = i
		return {fid: i for fid, i in self._features.items() if i is not None}

	def name(self):
		if not self.has(NAME):
			return ''
		length = self.call(NAME, 0)[0]
		out = b''
		while len(out) < length:
			chunk = self.call(NAME, 1, bytes([len(out)]))
			out += chunk[:length - len(out)]
		return out.split(b'\0')[0].decode('utf-8', 'replace')

	def kind(self):
		if not self.has(NAME):
			return ''
		try:
			return KINDS.get(self.call(NAME, 2)[0], '')
		except HidppError:
			return ''

	def firmware(self):
		"""Main firmware as text, e.g. 'U1 12.02.B0007', or ''."""
		if not self.has(FIRMWARE):
			return ''
		count = self.call(FIRMWARE, 0)[0]
		for entity in range(count):
			r = self.call(FIRMWARE, 1, bytes([entity]))
			if r[0] & 0x0F == 0:  # main application
				prefix = r[1:4].decode('ascii', 'replace').strip('\0 ')
				return f'{prefix} {r[4]:02X}.{r[5]:02X}.B{struct.unpack(">H", r[6:8])[0]:04X}'
		return ''


# --- finding the HID++ interface of a USB device ---------------------------------------------

SYS_HIDRAW = '/sys/class/hidraw'


def _descriptor_reports(desc):
	"""Report ids declared in a HID report descriptor (walks the short items)."""
	ids, i = set(), 0
	vendor = False
	while i < len(desc):
		prefix = desc[i]
		if prefix == 0xFE:  # long item
			i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
			continue
		size = (0, 1, 2, 4)[prefix & 3]
		data = int.from_bytes(desc[i + 1:i + 1 + size], 'little')
		tag = prefix & 0xFC
		if tag == 0x84:
			ids.add(data)
		elif tag == 0x04 and data >= 0xFF00:
			vendor = True
		i += 1 + size
	return ids, vendor


def hidraw_for(usb_port):
	"""[(path, HID++ report ids)] for the HID++ interfaces of a USB device (port like '3-2')."""
	found = []
	try:
		names = sorted(os.listdir(SYS_HIDRAW))
	except OSError:
		return found
	for name in names:
		real = os.path.realpath(os.path.join(SYS_HIDRAW, name, 'device'))
		if f'/{usb_port}:' not in real:
			continue
		try:
			with open(os.path.join(SYS_HIDRAW, name, 'device', 'report_descriptor'), 'rb') as f:
				ids, vendor = _descriptor_reports(f.read())
		except OSError:
			continue
		if vendor and (LONG in ids or SHORT in ids):
			found.append((f'/dev/{name}', ids & {SHORT, LONG, VERY_LONG}))
	return found


def open_usb(usb_port, index=CORDED):
	"""A Device for the HID++ interface of a USB device, or raises OSError. Index 0xFF is a
	corded device or the receiver itself; 1-6 a device paired to the receiver."""
	last = OSError(errno.ENODEV, 'no HID++ interface')
	for path, reports in hidraw_for(usb_port):
		try:
			dev = Device(HidrawTransport(path), index, reports)
		except OSError as e:
			last = e
			continue
		try:
			dev.protocol_version()
			return dev
		except HidppError:
			dev.close()
	raise last


def open_receiver(usb_port):
	"""(transport, reports) of a receiver's HID++ interface, to address its slots with
	Device(transport, index, reports). Raises OSError."""
	for path, reports in hidraw_for(usb_port):
		try:
			return HidrawTransport(path), reports
		except OSError:
			continue
	raise OSError(errno.ENODEV, 'no HID++ interface')
