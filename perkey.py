"""Per-key lighting over HID++ (0x8081 PerKeyLighting v2, and 0x8080 on older keyboards such as the
G910, G810 and G410), the way G HUB's agent drives them.

G HUB (feature_8081_led_lighting) turns each key of its layout (metadata.json: a PerKey type and
an id) into a zone number, sends the colours four keys at a time with SetIndividualRgbZones
(function 1: zone, r, g, b per key) and closes the frame with FrameEnd (function 7: persistence,
then two 16-bit big-endian numbers it leaves at 0). The zone numbers come from its built-in table
below; a device's light_map resource (light_map.json in its depot, which newer keyboards ship)
overrides it key by key: perKey -> PerKey type -> mapping {id: {"ledIndex": zone}}.
"""
import json
import struct

import depots
import hidpp
import store

_PATH_ARGS = {'M': 2, 'L': 2, 'T': 2, 'H': 1, 'V': 1, 'C': 6, 'S': 4, 'Q': 4}


def _path_commands(d):
	"""(command letter, its numbers) of an SVG path, repeated commands split (M then implicit L)."""
	import re
	cmd, args = None, []
	for tok in re.findall(r'[A-Za-z]|[-+]?[\d.]+(?:[eE][-+]?\d+)?', d):
		if tok.isalpha():
			cmd, args = (tok if tok.upper() in _PATH_ARGS else None), []
			continue
		if cmd is None:
			continue
		args.append(float(tok))
		if len(args) == _PATH_ARGS[cmd.upper()]:
			yield cmd, args
			args = []
			cmd = {'M': 'L', 'm': 'l'}.get(cmd, cmd)


def _path_points(d):
	"""Every point of an SVG path in absolute coordinates (control points too)."""
	x = y = 0.0
	for cmd, a in _path_commands(d):
		dx, dy = (x, y) if cmd.islower() else (0.0, 0.0)
		kind = cmd.upper()
		if kind == 'H':
			x = a[0] + dx
		elif kind == 'V':
			y = a[0] + dy
		else:
			pts = [(a[i] + dx, a[i + 1] + dy) for i in range(0, len(a), 2)]
			yield from pts[:-1]
			x, y = pts[-1]
		yield x, y


def _path_box(d):
	"""(x, y, w, h) around an SVG path's points (ours, for placing the LED), or None."""
	pts = list(_path_points(d))
	if not pts:
		return None
	xs, ys = [p[0] for p in pts], [p[1] for p in pts]
	return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _box(r):
	"""(x, y, w, h) of a rendering: a rect, or a round LED (centre and radius -> its box, ours). G HUB
	writes circles as {"circle": {cx, cy, r}} or, on some mice, {"rect": {x, y, r}}."""
	rect = r.get('rect', {})
	if r.get('type') == 'rect':
		return rect['x'], rect['y'], rect['width'], rect['height']
	if r.get('type') == 'circle':
		c = r.get('circle') or {}
		cx, cy, rad = c.get('cx', rect.get('x')), c.get('cy', rect.get('y')), c.get('r', rect.get('r'))
		if None not in (cx, cy, rad):
			return cx - rad, cy - rad, 2 * rad, 2 * rad
	if r.get('type') == 'path' and r.get('d'):                # a shaped LED (the newer headsets' lights)
		return _path_box(r['d'])
	return None


def load_layout(model):
	"""(width, height, [(group, id, x, y, w, h)]) from G HUB's metadata, or None."""
	path = depots.metadata_path(model)
	try:
		with open(path) as f:
			image = json.load(f)['images'][0]
	except (OSError, ValueError, KeyError, IndexError):
		return None
	keys = [(zone['id'], comp['id'], *box) for zone in image.get('zones', []) for comp in zone.get('components', [])
	        for box in map(_box, comp.get('renderings', [])) if box]
	origin = image.get('origin', {})
	return origin.get('width', 1), origin.get('height', 1), keys


def load_light_map(model):
	"""{(PerKey type, id): zone} from the model's light_map.json, {} when it has none."""
	try:
		with open(depots.light_map_path(model)) as f:
			data = json.load(f)
	except (OSError, ValueError):
		return {}
	out = {}
	for name, group in (data.get('perKey') or {}).items():
		for key, entry in (group.get('mapping') or {}).items():
			if key.isdigit() and isinstance(entry, dict) and 'ledIndex' in entry:
				out[(TYPES.get(name, 0), int(key))] = int(entry['ledIndex'])
	return out


COLORS_FILE = 'perkey.json'      # in store.CONFIG_DIR: {model: {"<group>:<id>": [r, g, b]}}


def load_colors(model):
	return store._read_json(f'{store.CONFIG_DIR}/{COLORS_FILE}', {}).get(model, {})


def save_colors(model, colors):
	path = f'{store.CONFIG_DIR}/{COLORS_FILE}'
	data = store._read_json(path, {})
	data[model] = colors
	store._write_json(path, data)

PERKEY = 0x8081
PERKEY_V1 = 0x8080
SET_INDIVIDUAL, SET_SINGLE_VALUE, FRAME_END = 1, 6, 7
PER_REPORT = 4
# G HUB's SetRgbZonesSingleValue (fn 6): [r, g, b, zone ids...], one colour for up to 13 zones; a
# colour shared by this many keys or more goes that way (ours)
SINGLE_MAX, SINGLE_FROM = 13, 4

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


def zones(colors, light_map=None):
	"""[(zone, r, g, b)] for {"<PerKey type>:<id>": [r, g, b]}; keys without a zone are left out.
	light_map (load_light_map) overrides the default table for the keys it lists."""
	light_map = light_map or {}
	out = []
	for name, rgb in colors.items():
		kind, _sep, key = name.partition(':')
		if not key.isdigit():
			continue
		kind_id = (TYPES.get(kind, 0), int(key))
		zone = light_map[kind_id] if kind_id in light_map else zone_for(*kind_id)
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


# 0x0620 RGB host mode (the newer headsets' per-LED lighting over Centurion; G HUB's Feature0620RGBHostmode):
# fn 3 SetConsecutiveRgbZones [first, count, rgb x count], fn 4 SetRangeRgbZones [count, (first, last, rgb)
# x count], fn 5 SetRgbZonesSingleValue [rgb, count, zones], fn 6 FrameEnd [4 bytes], fn 7 / 8 get / set
# host mode [state]. Ours: host mode on = 1, frame end [persist, 0, 0, 0], at most SINGLE_MAX zones / ranges
# per message (as 0x8081).
HOST_MODE = 0x0620
HM_RANGE, HM_SINGLE, HM_FRAME_END, HM_SET_STATE = 4, 5, 6, 8


def apply_host_mode(dev, colors, persist=False, light_map=None):
	"""The colours over 0x0620, grouped like apply(); returns how many zones went one by one."""
	by_color = {}
	for e in zones(colors, light_map):
		by_color.setdefault(tuple(e[1:]), []).append(e[0])
	singles = []
	for rgb, ids in by_color.items():
		if len(ids) < SINGLE_FROM:
			singles += [(z, rgb) for z in ids]
			continue
		for i in range(0, len(ids), SINGLE_MAX):
			part = ids[i:i + SINGLE_MAX]
			dev.call(HOST_MODE, HM_SINGLE, bytes(rgb) + bytes([len(part)]) + bytes(part))
	for i in range(0, len(singles), SINGLE_MAX):
		part = singles[i:i + SINGLE_MAX]
		dev.call(HOST_MODE, HM_RANGE, bytes([len(part)]) + b''.join(bytes([z, z, *rgb]) for z, rgb in part))
	dev.call(HOST_MODE, HM_FRAME_END, bytes([1 if persist else 0, 0, 0, 0]))
	return len(singles)


def apply(dev, colors, persist=True, light_map=None):
	"""Send the colours and end the frame. persist is G HUB's FrameEnd persistence flag; light_map
	is the keyboard's own key -> LED overrides (load_light_map)."""
	if not dev.has(PERKEY) and dev.has(PERKEY_V1):
		return apply_v1(dev, colors, persist)
	by_color = {}
	for e in zones(colors, light_map):
		by_color.setdefault(tuple(e[1:]), []).append(e)
	entries = []
	for rgb, group in by_color.items():
		if len(group) < SINGLE_FROM:
			entries += group
			continue
		ids = [e[0] for e in group]
		for i in range(0, len(ids), SINGLE_MAX):
			dev.call(PERKEY, SET_SINGLE_VALUE, bytes(rgb) + bytes(ids[i:i + SINGLE_MAX]))
	for i in range(0, len(entries), PER_REPORT):
		batch = entries[i:i + PER_REPORT]
		reply = dev.call(PERKEY, SET_INDIVIDUAL, b''.join(bytes(e) for e in batch))
		if any(reply[4 * n] != e[0] for n, e in enumerate(batch)):   # G HUB checks the echo too
			raise OSError(f'keyboard did not take zones {[e[0] for e in batch]}')
	dev.call(PERKEY, FRAME_END, bytes([1 if persist else 0]) + struct.pack('>HH', 0, 0))
	return len(entries)
