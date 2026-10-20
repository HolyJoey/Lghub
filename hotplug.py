"""Cheap 'did something get plugged in?' checks for the engine: compare a sysfs directory's
entries with the last time. One directory listing, so it can run every loop."""
import os

SOUND = '/sys/class/sound'          # sound cards: headsets, mics, speakers
USB = '/sys/bus/usb/devices'        # USB devices: webcams, receivers, ...
HID = '/sys/bus/hid/devices'        # HID devices: USB, a receiver's paired devices, Bluetooth


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


def on_port(real, port):
	"""Whether a sysfs device path (resolved) belongs to a port: a USB port like '3-2' (its
	interfaces are '3-2:1.0', ...) or a HID device name like '0005:046D:B024.0007' (Bluetooth)."""
	return f'/{port}:' in real or real.endswith(f'/{port}')
