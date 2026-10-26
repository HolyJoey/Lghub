"""Keyboards' onboard macros: the 0x8102 MACROS_LIBRARY profile tag (0x113), as G HUB builds it
(re/notes/keyboard_profiles.txt):

- The tag = the macros one after another (MacrosTag 0x142b5ba40), each [macro id u16 BE, name length
  (at most 24), name, data length u16 BE, data] (0x142b5c8d0, parser 0x142b5c6f0). A key plays a macro
  through its base-layer row, whose params are the macro id.
- The data = the steps, each [opcode] + operands (FUN_1422fe080; counts from FUN_1422feb40), then 0xFF
  unless the last byte is already 0xFF. G HUB keeps a CRC-32 of the data on its side; it isn't in the tag.
- Steps (FUN_1422fe280): 0x40 delay [ms u16 BE], 0x41 / 0x42 mouse buttons down / up [mask u16 BE,
  1 << (button - 1)], 0x43 / 0x44 key down / up [modifiers, HID usage], 0x45 / 0x46 consumer down / up
  [usage u16 BE], 0x61 mouse move [x u16 BE, y u16 BE] (signed: ours); 0x20 / 0x21 / 0x60 carry operands whose meaning
  isn't read."""
import struct

MACROS_TAG = 0x113
NAME_MAX = 24
END = 0xFF
DELAY, MOUSE_DOWN, MOUSE_UP, KEY_DOWN, KEY_UP, CONSUMER_DOWN, CONSUMER_UP, MOUSE_MOVE = \
	0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x61
OPERANDS = {0x20: 1, 0x21: 1, **dict.fromkeys(range(0x40, 0x47), 2), 0x60: 4, 0x61: 4}


def parse_library(data):
	"""[(macro id, name, data)] from the tag's bytes; stops at a short or malformed entry."""
	out, at = [], 0
	while at + 3 <= len(data):
		mid, n = struct.unpack_from('>HB', data, at)
		if n > NAME_MAX or at + 3 + n + 2 > len(data):
			break
		name = data[at + 3:at + 3 + n].decode('utf-8', 'replace')
		size = struct.unpack_from('>H', data, at + 3 + n)[0]
		start = at + 5 + n
		if start + size > len(data):
			break
		out.append((mid, name, bytes(data[start:start + size])))
		at = start + size
	return out


def encode_library(macros):
	"""The tag's bytes for [(macro id, name, data)]."""
	out = b''
	for mid, name, data in macros:
		raw = name.encode('utf-8')[:NAME_MAX]
		out += struct.pack('>HB', mid, len(raw)) + raw + struct.pack('>H', len(data)) + data
	return out


def parse_steps(data):
	"""[(opcode, operand bytes)] up to the end marker."""
	steps, at = [], 0
	while at < len(data) and data[at] != END:
		op = data[at]
		n = OPERANDS.get(op, 0)
		steps.append((op, bytes(data[at + 1:at + 1 + n])))
		at += 1 + n
	return steps


def encode_steps(steps):
	"""The data bytes for [(opcode, operand bytes)], with G HUB's end marker."""
	out = b''.join(bytes([op]) + operands for op, operands in steps)
	return out if out.endswith(bytes([END])) else out + bytes([END])


def _buttons(p):
	mask = struct.unpack('>H', p)[0]
	return 'mouse button ' + ', '.join(str(b + 1) for b in range(16) if mask >> b & 1)


def _move(p):
	x, y = struct.unpack('>hh', p)
	return f'move mouse {x}, {y}'


_WORDS = {DELAY: lambda p, _n: f'wait {struct.unpack(">H", p)[0]} ms',
          KEY_DOWN: lambda p, n: f'{n.get(p[1], f"key {p[1]}")} down',
          KEY_UP: lambda p, n: f'{n.get(p[1], f"key {p[1]}")} up',
          MOUSE_DOWN: lambda p, _n: _buttons(p) + ' down', MOUSE_UP: lambda p, _n: _buttons(p) + ' up',
          CONSUMER_DOWN: lambda p, _n: f'media 0x{struct.unpack(">H", p)[0]:02X} down',
          CONSUMER_UP: lambda p, _n: f'media 0x{struct.unpack(">H", p)[0]:02X} up',
          MOUSE_MOVE: lambda p, _n: _move(p)}


def describe(step, key_names=None):
	"""A step in words (key names: {HID usage: name})."""
	op, p = step
	if op in _WORDS and len(p) == OPERANDS[op]:
		return _WORDS[op](p, key_names or {})
	return f'step 0x{op:02X}'
