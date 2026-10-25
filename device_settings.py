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

0x8102 onboard profiles (G HUB's Feature8102ModularProfileManagement, vtable at +0xe0
0x143e4c698) use the same protocol with other function numbers and a profile byte before the tag:
fn 4 session operation, fn 6 start tag read [profile, tag u16] (FUN_141fb9540 puts the profile
byte first when there is one), fn 7 read fragment [sequence], fn 9 / 10 / 11 write / fragment /
commit. Lghub only reads them (read_profile_tag); which function reports the active profile isn't
pinned down yet.
"""
import struct
import zlib

import hidpp

GLOBAL_SETTINGS = 0x8103
PROFILE_MANAGEMENT = 0x8102
PROFILE_SESSION, PROFILE_READ, PROFILE_READ_FRAGMENT = 4, 6, 7
START_SESSION, END_SESSION = 0, 3
POWER_SAVING, POWER_OFF = 1, 2
POWER_SAVING_MINUTES = (0, 1, 2, 5, 10, 15)
POWER_OFF_MINUTES = (0, 1, 2, 5, 10, 15, 30)
FIRST_DATA = 12
FRAGMENT = 15


class Session:
	def __init__(self, dev, feature=GLOBAL_SETTINGS, fn=5):
		self.dev, self.feature, self.fn = dev, feature, fn

	def __enter__(self):
		self.dev.call(self.feature, self.fn, bytes([START_SESSION]))
		return self

	def __exit__(self, *_exc):
		self.dev.call(self.feature, self.fn, bytes([END_SESSION]))
		return False


def read_profile_tag(dev, profile, tag):
	"""A 0x8102 onboard-profile tag's bytes (read only)."""
	with Session(dev, PROFILE_MANAGEMENT, PROFILE_SESSION):
		r = dev.call(PROFILE_MANAGEMENT, PROFILE_READ, bytes([profile]) + struct.pack('>H', tag))
		seq, length = r[0], struct.unpack('>H', r[1:3])[0]
		data = b''
		while len(data) < length:
			data += dev.call(PROFILE_MANAGEMENT, PROFILE_READ_FRAGMENT, bytes([seq]))[1:1 + FRAGMENT]
		return data[:length]


# G HUB's analog tags (IFeature8102AnalogProfileTag; values are its settings x 100, big-endian)
ACTUATION, RAPID_TRIGGER_ON, KEY_PRIORITY_ON = 0x120, 0x121, 0x122
KEY_ACTUATION, KEY_RAPID_TRIGGER, KEY_PRIORITY_PAIRS = 0x123, 0x124, 0x130
PRIORITY_FLAVORS = ('distance', 'last input', 'ordinal', 'reverse ordinal', 'neutral')


def analog_profile(dev, profile):
	"""{'actuation': x, 'rapid_trigger': bool, 'key_priority': bool, 'keys': {cidx: x},
	'rapid': {cidx: x}, 'pairs': [(cidx, cidx, flavor, fully pressed)]} of a profile; tags the
	keyboard doesn't have are left out."""
	def tag(t):
		try:
			return read_profile_tag(dev, profile, t)
		except (OSError, hidpp.HidppError, struct.error):
			return None
	out = {}
	if (d := tag(ACTUATION)) and len(d) >= 2:
		out['actuation'] = struct.unpack('>H', d[:2])[0] / 100
	for key, t in (('rapid_trigger', RAPID_TRIGGER_ON), ('key_priority', KEY_PRIORITY_ON)):
		if d := tag(t):
			out[key] = bool(d[0])
	for key, t in (('keys', KEY_ACTUATION), ('rapid', KEY_RAPID_TRIGGER)):
		if (d := tag(t)) is not None:
			out[key] = {d[i]: struct.unpack('>H', d[i + 1:i + 3])[0] / 100 for i in range(0, len(d) - 2, 3)}
	if (d := tag(KEY_PRIORITY_PAIRS)) is not None:
		out['pairs'] = [(d[i], d[i + 1], PRIORITY_FLAVORS[d[i + 2] & 7] if d[i + 2] & 7 < 5 else d[i + 2] & 7,
		                 bool(d[i + 3])) for i in range(0, len(d) - 3, 4)]
	return out


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
