"""Low-battery desktop notifications, like G HUB's: the background service checks the battery of
wireless devices now and then and warns when one drops to G HUB's LOW (30 %) or CRITICAL (15 %)
level (logi.protocol.wireless.Battery.Warning.Level), once per drop, not while charging.

How often it checks (every 5 minutes) is ours. config.json "battery_warnings": false turns it off,
like G HUB's low_battery_notifications_enabled.
"""
import time

import hidpp
import store

CHECK_EVERY = 300.0
LEVELS = ((15, 'critical'), (30, 'low'))      # G HUB's CRITICAL and LOW


def level(percent):
	"""'critical', 'low' or None for a battery percentage."""
	return next((name for limit, name in LEVELS if percent <= limit), None)


def notify(title, body):
	"""A desktop notification over org.freedesktop.Notifications; False if there's no server."""
	from gi.repository import Gio, GLib
	try:
		bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
		bus.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
		              'org.freedesktop.Notifications', 'Notify',
		              GLib.Variant('(susssasa{sv}i)', ('Lghub', 0, 'battery-caution', title, body, [], {}, -1)),
		              None, Gio.DBusCallFlags.NONE, 2000, None)
		return True
	except GLib.Error:
		return False


class Watch:
	"""Used by the engine."""

	def __init__(self, send=notify):
		self.send = send
		self.last = 0.0
		self.warned = {}        # device id -> level last warned about

	def due(self, now):
		return now - self.last >= CHECK_EVERY

	def check(self, now=None):
		self.last = now if now is not None else time.monotonic()
		if not store.load_config().get('battery_warnings', True):
			return
		for device, reading in self._readings():
			self.update(device, reading)

	def update(self, device, reading):
		"""One battery reading (percent, text) for a device; warns when it fell to a new level."""
		percent, text = reading
		if percent is None:
			return
		charging = text.lower().startswith(('charging', 'almost', 'charged'))
		now = None if charging else level(percent)
		before = self.warned.get(device.id)
		if now and now != before and (before is None or now == 'critical'):
			self.send(f'{device.name}: battery {now}', f'{percent} % left. Charge it soon.')
		self.warned[device.id] = now

	def _readings(self):
		import battery_model
		import devices
		import features
		for d in self._wireless(devices):
			try:
				dev = devices.open_hidpp(d)
			except OSError:
				continue
			try:
				curves = battery_model.for_device(d) if dev.has(features.BATTERY_VOLTAGE) else None
				reading = features.battery(dev, curves)
			except (OSError, hidpp.HidppError):
				reading = None
			finally:
				dev.close()
			if reading:
				yield d, reading

	@staticmethod
	def _wireless(devices):
		for d in devices.discover():
			if d.model.type != 'receiver':
				if 'battery' in d.model.flags:
					yield d
				continue
			try:
				yield from devices.scan_receiver(d)
			except OSError:
				continue
