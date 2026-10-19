"""Which keys are down, read from a keyboard's own HID input reports (its hidraw nodes, open
through Lghub's udev rule), for G HUB's Echo press effect: G HUB follows key presses with its input
tracker; Lghub reads the keyboard itself (ours). Keys come out as HID usages (Keyboard page 0x07),
the same ids the per-key lighting uses.

Both report kinds keyboards use: arrays of usages (6-key rollover) and one bit per key (n-key).
"""
import os
import select
import threading

import surface_tuning

KEYBOARD_PAGE = 0x07


def key_fields(desc):
	"""{report id (0 = none): [(kind, offset, size, count, first usage)]} for the keyboard-page
	inputs of a HID report descriptor; kind 'bits' (one bit per usage) or 'array'."""
	state = {'page': 0, 'size': 0, 'count': 0, 'id': 0, 'min': 0, 'max': 0}
	offsets, fields = {}, {}
	for tag, data, _size in surface_tuning._items(desc):
		if tag in surface_tuning.GLOBALS:
			state[surface_tuning.GLOBALS[tag]] = data
		elif tag == 0x18:
			state['min'] = data
		elif tag == 0x28:
			state['max'] = data
		elif tag == 0x80:
			rid = state['id']
			start = offsets.get(rid, 0)
			offsets[rid] = start + state['size'] * state['count']
			if state['page'] == KEYBOARD_PAGE and not data & 1:
				kind = 'array' if not data & 2 else 'bits'
				fields.setdefault(rid, []).append((kind, start, state['size'], state['count'], state['min']))
			state['min'] = state['max'] = 0
		elif tag in (0x90, 0xB0, 0xA0, 0xC0):
			state['min'] = state['max'] = 0
	return fields


def keys_down(fields, report):
	"""The set of HID usages down in one input report, or None if it isn't a key report."""
	rid = report[0] if 0 not in fields else 0
	parts = fields.get(rid)
	if not parts:
		return None
	body = int.from_bytes(report[1:] if rid else report, 'little')
	down = set()
	for kind, offset, size, count, first in parts:
		for i in range(count):
			v = body >> (offset + i * size) & ((1 << size) - 1)
			if kind == 'bits' and v:
				down.add(first + i)
			elif kind == 'array' and v > 3:            # 0-3: none / rollover errors
				down.add(v)
	return down


def key_nodes(usb_port):
	"""[(path, fields)] of a USB device's hidraw nodes that report keys."""
	found = []
	try:
		names = sorted(os.listdir(surface_tuning.SYS_HIDRAW))
	except OSError:
		return found
	for name in names:
		real = os.path.realpath(os.path.join(surface_tuning.SYS_HIDRAW, name, 'device'))
		if f'/{usb_port}:' not in real:
			continue
		try:
			with open(os.path.join(surface_tuning.SYS_HIDRAW, name, 'device', 'report_descriptor'), 'rb') as f:
				fields = key_fields(f.read())
		except OSError:
			continue
		if fields:
			found.append((f'/dev/{name}', fields))
	return found


class Keys:
	"""Calls on_press(usage) for every key that goes down, on its own thread."""

	def __init__(self, nodes, on_press):
		self.on_press = on_press
		self.stop_event = threading.Event()
		self.files = []
		for path, fields in nodes:
			try:
				self.files.append((os.open(path, os.O_RDONLY | os.O_NONBLOCK), fields))
			except OSError:
				continue
		self.thread = threading.Thread(target=self._run, daemon=True)

	def start(self):
		if not self.files:
			raise OSError('can’t read the keyboard’s keys (udev rule missing?)')
		self.thread.start()

	def stop(self):
		self.stop_event.set()
		if self.thread.is_alive():
			self.thread.join(1)
		for fd, _f in self.files:
			os.close(fd)

	def _run(self):
		fds = dict(self.files)
		held = {fd: set() for fd in fds}
		while not self.stop_event.is_set():
			ready, _w, _x = select.select(list(fds), [], [], 0.1)
			for fd in ready:
				try:
					report = os.read(fd, 64)
				except OSError:
					continue
				down = keys_down(fds[fd], report)
				if down is None:
					continue
				for usage in down - held[fd]:
					self.on_press(usage)
				held[fd] = down
