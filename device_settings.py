"""Power timers through 0x8103 GlobalDeviceSettings, G HUB's tag protocol (FeatureTagManager, the
same one 0x8102 onboard profiles use).

From G HUB's agent:
- fn 5 (operation): START_SESSION = 0, END_SESSION = 3; reads and writes run inside a session.
- fn 3 start tag read [tag u16] -> [sequence, length u16]; fn 4 read fragment [sequence] ->
  [sequence, 15 data bytes], until length bytes are in.
- fn 6 start tag write [tag u16, size u16, data]; fn 7 write fragment [sequence, 15 bytes];
  fn 8 commit [CRC-32 of the data, u32] -> [status, ...], status 0 = written. The CRC is the
  standard (zlib) one, G HUB's FUN_142010280.
- Tag 1 PowerSavingTimeoutTag, tag 2 PowerOffTimeoutTag: seconds, u16. G HUB's choices in minutes:
  power saving Never / 1 / 2 / 5 / 10 / 15, power off Never / 1 / 2 / 5 / 10 / 15 / 30 (mice with
  the advanced sleep timer; Never / 5 / 15 / 30 / 60 otherwise). Never = 0.

Ours: the first data bytes ride in fn 6 (12 fit), and fragments carry fn 6's answer byte.
"""
import struct
import zlib

import hidpp

GLOBAL_SETTINGS = 0x8103
START_SESSION, END_SESSION = 0, 3
POWER_SAVING, POWER_OFF = 1, 2
POWER_SAVING_MINUTES = (0, 1, 2, 5, 10, 15)
POWER_OFF_MINUTES = (0, 1, 2, 5, 10, 15, 30)
FIRST_DATA = 12
FRAGMENT = 15


class Session:
	def __init__(self, dev):
		self.dev = dev

	def __enter__(self):
		self.dev.call(GLOBAL_SETTINGS, 5, bytes([START_SESSION]))
		return self

	def __exit__(self, *_exc):
		self.dev.call(GLOBAL_SETTINGS, 5, bytes([END_SESSION]))
		return False


def read_tag(dev, tag):
	with Session(dev):
		r = dev.call(GLOBAL_SETTINGS, 3, struct.pack('>H', tag))
		seq, length = r[0], struct.unpack('>H', r[1:3])[0]
		data = b''
		while len(data) < length:
			data += dev.call(GLOBAL_SETTINGS, 4, bytes([seq]))[1:1 + FRAGMENT]
		return data[:length]


def write_tag(dev, tag, data):
	with Session(dev):
		r = dev.call(GLOBAL_SETTINGS, 6, struct.pack('>HH', tag, len(data)) + data[:FIRST_DATA])
		seq = r[0]
		for i in range(FIRST_DATA, len(data), FRAGMENT):
			dev.call(GLOBAL_SETTINGS, 7, bytes([seq]) + data[i:i + FRAGMENT].ljust(FRAGMENT, b'\0'))
		status = dev.call(GLOBAL_SETTINGS, 8, struct.pack('>I', zlib.crc32(data)))[0]
	if status:
		raise OSError(f'the device didn’t take the setting (status {status})')


def timeout(dev, tag):
	"""A power timer in seconds (0 = never)."""
	return struct.unpack('>H', read_tag(dev, tag)[:2])[0]


def set_timeout(dev, tag, seconds):
	write_tag(dev, tag, struct.pack('>H', max(0, min(0xFFFF, int(seconds)))))


def power_timers(dev):
	"""{tag: seconds} for the timers the device answers for."""
	out = {}
	for tag in (POWER_SAVING, POWER_OFF):
		try:
			out[tag] = timeout(dev, tag)
		except (OSError, hidpp.HidppError, struct.error):
			continue
	return out
