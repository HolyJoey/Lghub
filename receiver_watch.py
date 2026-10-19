"""Wakes the background service the moment a wireless device switches on, instead of waiting for
the next poll: one thread per receiver reads its HID++ interface for the device-connection
notification (HID++ 1.0 report 0x10 / 0x11, sub id 0x41; bit 6 of the flags byte set = link not
established), as G HUB's AccessoryBus does on plug. The layout is from Logitech's HID++ 1.0
receiver spec. Several readers on one hidraw node each get every report, so this doesn't take
anything from the other parts of the service.
"""
import threading

import hidpp

CONNECTION = 0x41
LINK_DOWN = 0x40


def connected(report):
	"""The device index of a "device switched on" notification, else None."""
	if len(report) >= 5 and report[0] in (hidpp.SHORT, hidpp.LONG) and report[2] == CONNECTION:
		return None if report[4] & LINK_DOWN else report[1]
	return None


class Watch:
	"""Used by the engine: changed() is True once after any device behind a receiver comes on."""

	def __init__(self):
		self.event = threading.Event()
		self.threads = {}          # receiver port -> thread
		self.stop_event = threading.Event()

	def changed(self):
		if self.event.is_set():
			self.event.clear()
			return True
		return False

	def follow(self, receivers):
		"""Start listening to receivers not followed yet (devices.Device entries)."""
		for r in receivers:
			alive = self.threads.get(r.port)
			if alive and alive.is_alive():
				continue
			try:
				transport, _reports = hidpp.open_receiver(r.port)
			except OSError:
				continue
			t = threading.Thread(target=self._listen, args=(transport,), daemon=True)
			self.threads[r.port] = t
			t.start()

	def stop(self):
		self.stop_event.set()

	def _listen(self, transport):
		try:
			while not self.stop_event.is_set():
				report = transport.read(1.0)
				if report and connected(report) is not None:
					self.event.set()
		except OSError:
			pass                          # unplugged
		finally:
			transport.close()
