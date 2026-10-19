"""Surface tuning (HID++ 0x2240): calibrates the mouse's sensor to the pad it's on, as G HUB's
feature_2240_surface_tuning does it.

G HUB's sequence: fn 2 then fn 3 start it; you move the mouse around; after 20 units of movement
the mouse reports its shutter calibration (event 0: [status, LED drive], status 0 = done) and
fn 4 starts the surface-quality ("squal") calibration; after 65 more units fn 5 stops it and the
mouse reports [status, pixel threshold, minimum squal] (event 1); fn 6 ends tuning either way.
A unit is 200 mouse counts; G HUB asks for 4-18 units a second (slower / faster hints
otherwise). fn 1 sets [LED drive, pixel threshold, minimum squal], the three values G HUB keeps
for a tuned surface; Lghub sends them after a successful run and when you pick a saved surface.

G HUB measures the movement from the computer's pointer; Lghub reads the mouse's own motion
reports from its hidraw nodes (ours), so nothing outside the mouse is needed. The timeouts and
the averaging window are ours.

surfaces.json in the config folder: {device serial or id: [{"name", "values": [3 bytes]}]}.
"""
import os
import select
import threading
import time

import store

SURFACE_TUNING = 0x2240
EV_SHUTTER_DONE, EV_SQUAL_DONE = 0, 1
COUNTS_PER_UNIT = 200.0
STAGES = (20, 65)                   # units of movement per stage
SPEED_MIN, SPEED_MAX = 4.0, 18.0    # units per second
GOOD, SLOWER, FASTER = 1, 2, 3      # G HUB's Speed.Suggestion
EVENT_TIMEOUT = 10.0
WINDOW = 0.25
FILE = os.path.join(store.CONFIG_DIR, 'surfaces.json')
SYS_HIDRAW = '/sys/class/hidraw'


def load(key):
	return store._read_json(FILE, {}).get(key, [])


def save(key, surfaces):
	data = store._read_json(FILE, {})
	data[key] = surfaces
	store._write_json(FILE, data)


def apply(dev, values):
	dev.call(SURFACE_TUNING, 1, bytes(values[:3]))


def info(dev):
	"""(values in use now, factory values) from fn 0's 9 bytes: G HUB's surface control matches
	bytes 3-5 against the saved surfaces to find the active one, and makes its factory surface
	from bytes 6-8 (bytes 0-2 it doesn't use there)."""
	r = dev.call(SURFACE_TUNING, 0)
	return list(r[3:6]), list(r[6:9])


def speed_hint(speed):
	if speed < SPEED_MIN:
		return FASTER
	return SLOWER if speed > SPEED_MAX else GOOD


# --- the mouse's motion reports --------------------------------------------------------------

def _item_value(prefix, data, size):
	if prefix & 0xFC in (0x14, 0x24) and size and data >> (8 * size - 1):   # signed logical min/max
		return data - (1 << 8 * size)
	return data


def _items(desc):
	"""(tag, value, size) of each short item of a HID report descriptor."""
	i = 0
	while i < len(desc):
		prefix = desc[i]
		if prefix == 0xFE:                      # long item
			i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
			continue
		size = (0, 1, 2, 4)[prefix & 3]
		yield prefix & 0xFC, _item_value(prefix, int.from_bytes(desc[i + 1:i + 1 + size], 'little'), size), size
		i += 1 + size


GLOBALS = {0x04: 'page', 0x74: 'size', 0x94: 'count', 0x84: 'id'}


def motion_fields(desc):
	"""{report id (0 = none): {'x': (offset, bits, relative), 'y': ...}}, offsets in bits after
	the id byte, for the relative X / Y inputs (Generic Desktop 0x30 / 0x31) of a HID report
	descriptor."""
	state = {'page': 0, 'size': 0, 'count': 0, 'id': 0}
	usages, offsets, fields = [], {}, {}
	for tag, data, size in _items(desc):
		if tag in GLOBALS:
			state[GLOBALS[tag]] = data
		elif tag == 0x08:
			usages.append(data if size == 4 else state['page'] << 16 | data)
		elif tag == 0x80:
			_input(fields, offsets, state['id'], usages, state['size'], state['count'], data)
			usages = []
		elif tag in (0x90, 0xB0, 0xA0, 0xC0):   # output, feature, collection, end
			usages = []
	return {r: f for r, f in fields.items() if 'x' in f and 'y' in f and f['x'][2] and f['y'][2]}


def _input(fields, offsets, rid, usages, rsize, rcount, flags):
	start = offsets.get(rid, 0)
	offsets[rid] = start + rsize * rcount
	if flags & 1:               # constant: padding
		return
	for n in range(rcount):
		usage = usages[min(n, len(usages) - 1)] if usages else 0
		axis = {0x10030: 'x', 0x10031: 'y'}.get(usage)
		if axis:
			fields.setdefault(rid, {})[axis] = (start + n * rsize, rsize, bool(flags & 4))   # bit 2: relative


def read_motion(fields, report):
	"""(dx, dy) from one input report, or None if it carries no motion."""
	rid = report[0] if 0 not in fields else 0
	f = fields.get(rid)
	if not f:
		return None
	body = int.from_bytes(report[1:] if rid else report, 'little')
	out = []
	for offset, bits, _relative in (f['x'], f['y']):
		v = body >> offset & ((1 << bits) - 1)
		out.append(v - (1 << bits) if v >> (bits - 1) else v)
	return tuple(out)


def motion_nodes(usb_port):
	"""[(path, fields)] of the hidraw nodes of a USB device that report X / Y motion."""
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
				fields = motion_fields(f.read())
		except OSError:
			continue
		if fields:
			found.append((f'/dev/{name}', fields))
	return found


class Motion:
	"""Adds up how far the mouse moves (in G HUB's units) from its own reports, in a thread."""

	def __init__(self, nodes):
		self.distance = 0.0
		self.lock = threading.Lock()
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
			raise OSError('can’t read the mouse’s movement (udev rule missing?)')
		self.thread.start()

	def stop(self):
		self.stop_event.set()
		if self.thread.is_alive():
			self.thread.join(1)
		for fd, _f in self.files:
			os.close(fd)

	def _run(self):
		fds = dict(self.files)
		while not self.stop_event.is_set():
			ready, _w, _x = select.select(list(fds), [], [], 0.1)
			for fd in ready:
				try:
					report = os.read(fd, 64)
				except OSError:
					continue
				d = read_motion(fds[fd], report)
				if d:
					with self.lock:
						self.distance += (d[0] ** 2 + d[1] ** 2) ** 0.5 / COUNTS_PER_UNIT


# --- the tuning run ---------------------------------------------------------------------------

class Cancelled(Exception):
	pass


def tune(dev, motion, progress, cancel):
	"""Runs G HUB's sequence on an open hidpp.Device with a started Motion. progress(fraction,
	speed, hint) is called a few times a second; cancel is a threading.Event. Returns
	[LED drive, pixel threshold, minimum squal], or raises Cancelled / OSError."""
	index = dev.feature_index(SURFACE_TUNING)
	total = float(sum(STAGES))
	done = 0.0
	dev.call(SURFACE_TUNING, 2)
	dev.call(SURFACE_TUNING, 3)
	try:
		_move(motion, STAGES[0], done, total, progress, cancel)
		done += STAGES[0]
		ok, led, _x = _wait_event(dev, index, EV_SHUTTER_DONE, cancel)
		if not ok:
			raise OSError('the mouse couldn’t calibrate on this surface (shutter)')
		dev.call(SURFACE_TUNING, 4)
		_move(motion, STAGES[1], done, total, progress, cancel)
		dev.call(SURFACE_TUNING, 5)
		ok, pixel, min_squal = _wait_event(dev, index, EV_SQUAL_DONE, cancel)
		if not ok:
			raise OSError('the mouse couldn’t calibrate on this surface (surface quality)')
	finally:
		dev.call(SURFACE_TUNING, 6)
	values = [led, pixel, min_squal]
	apply(dev, values)
	progress(1.0, 0.0, GOOD)
	return values


def _move(motion, units, done, total, progress, cancel):
	with motion.lock:
		start = motion.distance
	last_d, last_t = start, time.monotonic()
	while True:
		if cancel.wait(WINDOW):
			raise Cancelled()
		with motion.lock:
			now_d = motion.distance
		now_t = time.monotonic()
		speed = (now_d - last_d) / (now_t - last_t)
		last_d, last_t = now_d, now_t
		moved = min(units, now_d - start)
		progress((done + moved) / total, speed, speed_hint(speed))
		if moved >= units:
			return


def _wait_event(dev, index, event, cancel):
	deadline = time.monotonic() + EVENT_TIMEOUT
	while time.monotonic() < deadline:
		if cancel.is_set():
			raise Cancelled()
		got = dev.next_event(0.2)
		if got and got[0] == index and got[1] == event:
			p = got[2]
			return p[0] == 0, p[1], p[2]
	raise OSError('the mouse didn’t finish calibrating')
