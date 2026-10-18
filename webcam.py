"""Webcam settings that stick: UVC cameras forget them when unplugged, so they are saved per
camera and put back by the engine whenever the camera appears."""
import os
import time

import devices
import store
import v4l2

WEBCAM_FILE = os.path.join(store.CONFIG_DIR, 'webcams.json')
CHECK_EVERY = 3.0
SETTLE = 1.0           # a fresh camera needs a moment before it takes controls


def ident(device):
	return f'{device.usb_id}:{device.serial}' if device.serial else device.usb_id


def load_all():
	return store._read_json(WEBCAM_FILE, {})


def saved(device):
	return load_all().get(ident(device), {})


def remember(device, key, value):
	data = load_all()
	data.setdefault(ident(device), {})[key] = value
	store._write_json(WEBCAM_FILE, data)


def forget(device):
	data = load_all()
	if data.pop(ident(device), None) is not None:
		store._write_json(WEBCAM_FILE, data)


def apply(camera, values):
	"""Set saved values: switches and menus first (auto modes decide which manual controls
	are allowed), then the rest."""
	controls = camera.controls()
	for first in (True, False):
		if not first:
			controls = camera.controls()     # re-read: manual controls may be active now
		for c in controls:
			if c.key not in values or c.read_only or (c.kind == v4l2.T_INTEGER) == first:
				continue
			if not first and c.inactive:
				continue
			try:
				camera.set(c.id, values[c.key])
			except OSError:
				pass


class Restorer:
	"""Used by the engine: applies saved settings to cameras as they are plugged in."""

	def __init__(self):
		self.seen = {}           # device id -> time first seen
		self.done = set()
		self.last_check = 0.0

	def due(self):
		return time.monotonic() - self.last_check >= CHECK_EVERY

	def check(self):
		self.last_check = now = time.monotonic()
		cams = [d for d in devices.discover() if d.model.type == 'camera' and not d.id.startswith('usb:fake')]
		present = {d.id for d in cams}
		for gone in set(self.seen) - present:
			self.seen.pop(gone)
			self.done.discard(gone)
		all_saved = load_all() if cams else {}
		for d in cams:
			self.seen.setdefault(d.id, now)
			values = all_saved.get(ident(d))
			if d.id in self.done or not values or now - self.seen[d.id] < SETTLE:
				continue
			node = v4l2.video_node(d.id.split(':', 1)[1])
			if not node:
				continue
			try:
				cam = v4l2.Camera(node)
			except OSError:
				continue
			try:
				apply(cam, values)
			finally:
				cam.close()
			self.done.add(d.id)
			print(f'engine: restored {len(values)} settings on {d.name}', flush=True)
