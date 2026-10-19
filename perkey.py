"""Per-key lighting over HID++ (0x8081 PerKeyLighting v2), the way G HUB's agent drives it.

G HUB (feature_8081_led_lighting) turns each key of its layout (metadata.json: a PerKey type and
an id) into a zone number, sends the colours four keys at a time with SetIndividualRgbZones
(function 1: zone, r, g, b per key) and closes the frame with FrameEnd (function 7: persistence,
then two 16-bit big-endian numbers it leaves at 0). The zone numbers come from its built-in table
below; a device's light_map resource can override it, but none of the depots we know ships one.
"""
import struct

PERKEY = 0x8081
SET_INDIVIDUAL, FRAME_END = 1, 7
PER_REPORT = 4

# G HUB's PerKey.Type values (lighting_support.proto)
KEYBOARD, CONSUMER, GKEY, BRANDING, INDICATOR = 1, 2, 4, 16, 32
TYPES = {'PERKEY_KEYBOARD': KEYBOARD, 'PERKEY_CONSUMER': CONSUMER, 'PERKEY_GKEY': GKEY,
         'PERKEY_BRANDING': BRANDING, 'PERKEY_INDICATOR': INDICATOR, 'PERKEY_COSMETIC': 64,
         'PERKEY_COSMETIC_2': 128, 'PERKEY_COSMETIC_3': 256, 'PERKEY_COSMETIC_4': 512}


def zone_for(kind, key):
	"""The 0x8081 zone of a key (its PerKey type and layout id), or None: G HUB's default table."""
	if kind == KEYBOARD:   # HID keyboard usages
		zone = key - 3 if key < 0x66 else key - 0x24 if key < 0x8C else key - 0x78
	elif kind == CONSUMER:
		zone = key - 0x18 if key < 0xB8 else key - 0x32 if key < 0xCE else key - 0x46 if key < 0xE3 else -1
	elif kind == GKEY:
		zone = key + 0xB3
	elif kind == BRANDING:
		zone = key + 0xD1
	elif kind == INDICATOR:
		zone = key + 0x98 if key <= 2 else key + 0x93
	elif kind in (64, 128, 256, 512):
		zone = key
	else:
		zone = -1
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


def apply(dev, colors, persist=True):
	"""Send the colours and end the frame. persist is G HUB's FrameEnd persistence flag."""
	entries = zones(colors)
	for i in range(0, len(entries), PER_REPORT):
		batch = entries[i:i + PER_REPORT]
		reply = dev.call(PERKEY, SET_INDIVIDUAL, b''.join(bytes(e) for e in batch))
		if any(reply[4 * n] != e[0] for n, e in enumerate(batch)):   # G HUB checks the echo too
			raise OSError(f'keyboard did not take zones {[e[0] for e in batch]}')
	dev.call(PERKEY, FRAME_END, bytes([1 if persist else 0]) + struct.pack('>HH', 0, 0))
	return len(entries)
