"""Per-key lighting over HID++ (0x8081 PerKeyLighting v2, and 0x8080 on older keyboards such as the
G910, G810 and G410), the way G HUB's agent drives them.

G HUB (feature_8081_led_lighting) turns each key of its layout (metadata.json: a PerKey type and
an id) into a zone number, sends the colours four keys at a time with SetIndividualRgbZones
(function 1: zone, r, g, b per key) and closes the frame with FrameEnd (function 7: persistence,
then two 16-bit big-endian numbers it leaves at 0). The zone numbers come from its built-in table
below; a device's light_map resource can override it, but none of the depots we know ships one.
"""
import struct

import hidpp

PERKEY = 0x8081
PERKEY_V1 = 0x8080
SET_INDIVIDUAL, FRAME_END = 1, 7
PER_REPORT = 4

# G HUB's PerKey.Type values (lighting_support.proto)
KEYBOARD, CONSUMER, GKEY, BRANDING, INDICATOR = 1, 2, 4, 16, 32
TYPES = {'PERKEY_KEYBOARD': KEYBOARD, 'PERKEY_CONSUMER': CONSUMER, 'PERKEY_GKEY': GKEY,
         'PERKEY_BRANDING': BRANDING, 'PERKEY_INDICATOR': INDICATOR, 'PERKEY_COSMETIC': 64,
         'PERKEY_COSMETIC_2': 128, 'PERKEY_COSMETIC_3': 256, 'PERKEY_COSMETIC_4': 512}


# G HUB's default key -> zone table (FUN_14219f320): per PerKey type, (ids below, offset) in order;
# ids past the last limit have no zone.
ZONE_OFFSETS = {
	KEYBOARD: ((0x66, -3), (0x8C, -0x24), (0x100, -0x78)),        # HID keyboard usages
	CONSUMER: ((0xB8, -0x18), (0xCE, -0x32), (0xE3, -0x46)),
	GKEY: ((0x100, 0xB3),),
	BRANDING: ((0x100, 0xD1),),
	INDICATOR: ((3, 0x98), (0x100, 0x93)),
	64: ((0x100, 0),), 128: ((0x100, 0),), 256: ((0x100, 0),), 512: ((0x100, 0),),   # cosmetic
}


def zone_for(kind, key):
	"""The 0x8081 zone of a key (its PerKey type and layout id), or None."""
	offset = next((off for below, off in ZONE_OFFSETS.get(kind, ()) if key < below), None)
	if offset is None:
		return None
	zone = key + offset
	return zone if 0 < zone < 0x100 else None


def zones(colors):
	"""[(zone, r, g, b)] for {"<PerKey type>:<id>": [r, g, b]}; keys without a zone are left out."""
	out = []
	for name, rgb in colors.items():
		kind, _sep, key = name.partition(':')
		zone = zone_for(TYPES.get(kind, 0), int(key)) if key.isdigit() else None
		if zone is not None:
			out.append((zone, *(max(0, min(255, int(c))) for c in rgb[:3])))
	return sorted(out)


# 0x8080 (G HUB's Feature8080PerKeyLighting / feature_8080_key_lighting): fn 0 info (first two
# bytes: the key types the keyboard has, as bits), fn 3 SetKeyColors (key type u16, count u16,
# then key, r, g, b; G HUB sends up to 14 at a time), fn 5 Flush (persistence). The key byte is
# the layout's own id; the type is G HUB's firmware_lighting PerKey.Type as a bit: HID keyboard 1,
# consumer 2, G-key 4, generic button 8, logo 0x10, other keyboard keys 0x40. Which layout group
# is which type comes from G HUB's per-device configuration; the pairing below goes by the names
# (ours; indicators as "other keyboard keys").
V1_TYPES = {KEYBOARD: 0x01, CONSUMER: 0x02, GKEY: 0x04, 8: 0x08, BRANDING: 0x10, INDICATOR: 0x40}
V1_SET, V1_FLUSH = 3, 5
V1_MAX = 14


def keys_v1(colors, supported):
	"""{key type bit: [(key, r, g, b)]} for the types the keyboard has."""
	out = {}
	for name, rgb in colors.items():
		kind, _sep, key = name.partition(':')
		bit = V1_TYPES.get(TYPES.get(kind, 8 if kind == 'PERKEY_GENERIC' else 0))
		if bit and bit & supported and key.isdigit() and 0 <= int(key) < 0x100:
			out.setdefault(bit, []).append((int(key), *(max(0, min(255, int(c))) for c in rgb[:3])))
	return {bit: sorted(entries) for bit, entries in out.items()}


def apply_v1(dev, colors, persist=True):
	supported = struct.unpack('>H', dev.call(PERKEY_V1, 0)[:2])[0]
	# 14 per request needs 64-byte reports; with 20-byte ones 3 fit (ours)
	per = V1_MAX if hidpp.VERY_LONG in dev.reports else 3
	sent = 0
	for bit, entries in keys_v1(colors, supported).items():
		for i in range(0, len(entries), per):
			batch = entries[i:i + per]
			dev.call(PERKEY_V1, V1_SET, struct.pack('>HH', bit, len(batch)) + b''.join(bytes(e) for e in batch))
			sent += len(batch)
	dev.call(PERKEY_V1, V1_FLUSH, bytes([1 if persist else 0]))
	return sent


def apply(dev, colors, persist=True):
	"""Send the colours and end the frame. persist is G HUB's FrameEnd persistence flag."""
	if not dev.has(PERKEY) and dev.has(PERKEY_V1):
		return apply_v1(dev, colors, persist)
	entries = zones(colors)
	for i in range(0, len(entries), PER_REPORT):
		batch = entries[i:i + PER_REPORT]
		reply = dev.call(PERKEY, SET_INDIVIDUAL, b''.join(bytes(e) for e in batch))
		if any(reply[4 * n] != e[0] for n, e in enumerate(batch)):   # G HUB checks the echo too
			raise OSError(f'keyboard did not take zones {[e[0] for e in batch]}')
	dev.call(PERKEY, FRAME_END, bytes([1 if persist else 0]) + struct.pack('>HH', 0, 0))
	return len(entries)
