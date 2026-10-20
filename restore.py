"""Puts devices' saved settings back when they appear, as G HUB re-applies them when a device
connects or wakes up (its 0x1D4B reconnection handling): per-key colours and game-mode keys.

A device counts as appearing when it is plugged in, or when its receiver says it switched on
(receiver_watch.py), with a look every CHECK_EVERY seconds as a fallback while something is
saved; listening to the receiver rather than to 0x1D4B on each device is ours.
"""
import time

import features
import hidpp
import hotplug
import perkey
import store

CHECK_EVERY = 60.0


def saved_for(model):
	"""(per-key colours, game-mode keys) saved for a model."""
	return perkey.load_colors(model), features.game_mode_keys(model)


def anything_saved():
	return any(store._read_json(f'{store.CONFIG_DIR}/{name}', {}).values()
	           for name in (perkey.COLORS_FILE, features.GAME_MODE_FILE))


def apply_saved(dev, model):
	"""Put a model's saved settings on an open device; the features it lacks are skipped."""
	colors, keys = saved_for(model)
	if colors and (dev.has(perkey.PERKEY) or dev.has(perkey.PERKEY_V1)):
		perkey.apply(dev, colors)
	if keys and (dev.has(features.DISABLE_KEYS) or dev.has(features.DISABLE_KEYS_V1)):
		features.apply_game_mode(dev, keys)


class Restorer:
	"""Used by the engine."""

	def __init__(self):
		import receiver_watch
		self.hid = hotplug.Watch(hotplug.HID)
		self.wireless = receiver_watch.Watch()
		self.present = set()       # device ids seen last time
		self.last = 0.0

	def due(self, now):
		return self.hid.changed() or self.wireless.changed() or now - self.last >= CHECK_EVERY

	def check(self, now=None):
		import devices
		self.last = now if now is not None else time.monotonic()
		if not anything_saved():
			self.present = set()
			return
		found = {}
		present = devices.discover()
		self.wireless.follow([d for d in present if d.model.type == 'receiver'])
		for d in present:
			if d.model.type != 'receiver':
				found[d.id] = d
				continue
			if anything_saved():
				try:
					found.update({p.id: p for p in devices.scan_receiver(d)})
				except OSError:
					continue
		for dev_id in set(found) - self.present:
			d = found[dev_id]
			if not any(saved_for(d.model.key)):
				continue
			try:
				dev = devices.open_hidpp(d)
				try:
					apply_saved(dev, d.model.key)
					print(f'engine: settings back on {d.name}', flush=True)
				finally:
					dev.close()
			except (OSError, hidpp.HidppError) as e:
				print(f'engine: could not restore {d.name}: {e}', flush=True)
		self.present = set(found)
