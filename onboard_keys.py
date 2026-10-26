"""Keyboards' onboard key assignments: the 0x8102 base-layer tag (INPUT_CONFIGURATION, 0x110), as G HUB
writes its key rows (re/notes/keyboard_profiles.txt):

- [group count] then per key [control index, row count] and its rows (AssignmentsBaseLayerTag
  0x142b62090; inputPresetToFkcGroups 0x142368f20 fills the group from the CidMap index and the row count).
- A row is [row index, trigger modifiers u16 BE, action bits u16 BE, opcode u16 BE, params u16 BE]; G HUB
  adds a mirrored row with left / right modifiers swapped (0x142300820).
- Opcodes (cardIdToFkcRow 0x142365410): 0x8002 key (action bits = its modifiers, params = HID usage),
  0x8000 modifiers only, 0x8001 mouse buttons (params = mask), 0x8003 media (params = consumer usage),
  0x9001 / 0x9002 wheel left / right, 0x9003-0x9007 DPI up / down / cycle / default / shift,
  0x9008-0x900A profile next / previous / cycle, 0x900C battery, 0x9017 report rate cycle.
Whether a plain read of 0x110 returns just these rows isn't checked (the tag also has analog groups in
another part), so Lghub only shows a parse that uses the bytes up exactly."""
import struct

BASE_LAYER_TAG = 0x110
ROW = struct.Struct('>BHHHH')
OPCODES = {0x8000: 'modifiers', 0x8001: 'mouse buttons', 0x8003: 'media', 0x9001: 'wheel left',
           0x9002: 'wheel right', 0x9003: 'DPI up', 0x9004: 'DPI down', 0x9005: 'DPI cycle',
           0x9006: 'DPI default', 0x9007: 'DPI shift', 0x9008: 'next profile', 0x9009: 'previous profile',
           0x900A: 'cycle profiles', 0x900C: 'battery level', 0x9017: 'cycle report rate'}
KEY = 0x8002


def parse_base_layer(data):
	"""[(control index, [(row, modifiers, action bits, opcode, params)])], or None when the bytes
	aren't exactly that."""
	if not data:
		return None
	out, at = [], 1
	for _group in range(data[0]):
		if at + 2 > len(data):
			return None
		cidx, n = data[at], data[at + 1]
		at += 2
		if at + n * ROW.size > len(data):
			return None
		out.append((cidx, [ROW.unpack_from(data, at + i * ROW.size) for i in range(n)]))
		at += n * ROW.size
	return out if at == len(data) else None


def describe(row, key_names=None):
	"""A row's action in words."""
	_index, _mods, _bits, opcode, params = row
	if opcode == KEY:
		return (key_names or {}).get(params & 0xFF, f'key {params & 0xFF}')
	if opcode == 0x8001:
		return 'mouse button ' + ', '.join(str(b + 1) for b in range(16) if params >> b & 1)
	if opcode in OPCODES:
		return OPCODES[opcode] + (f' 0x{params:02X}' if opcode == 0x8003 else '')
	return f'action 0x{opcode:04X} ({params})'
