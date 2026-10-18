"""Cheap 'did something get plugged in?' checks for the engine: compare a sysfs directory's
entries with the last time. One directory listing, so it can run every loop."""
import os

SOUND = '/sys/class/sound'          # sound cards: headsets, mics, speakers
USB = '/sys/bus/usb/devices'        # USB devices: webcams, receivers, ...


class Watch:
	def __init__(self, path):
		self.path = path
		self.seen = None

	def changed(self):
		"""True the first time and whenever the set of entries differs from the last call."""
		try:
			now = frozenset(os.listdir(self.path))
		except OSError:
			now = frozenset()
		if now == self.seen:
			return False
		self.seen = now
		return True
