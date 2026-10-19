"""On-screen notices when a mouse changes profile, DPI level or report rate with its own buttons,
like G HUB's OSD_PROFILE_CHANGED, OSD_DPI_CHANGED and OSD_REPORT_RATE_CHANGED. Onboard-memory
mice (0x8100) send event 0 profile activated and event 1 active DPI changed (G HUB's
Feature8100OnboardProfiles::Report); the notice reads the mouse's current profile and DPI slot
back, and the DPI from its profile. Newer mice (0x8061) send event 0 [connection type, rate
number] (G HUB's ReportRateInfoEvent).

Each new notice replaces the last one, shown for 1.5 s (ours). config.json "osd_notifications":
false turns them off.
"""
import threading

import hidpp
import mouse
import store

PROFILE_ACTIVATED, DPI_CHANGED = 0, 1
RATE_CHANGED = 'rate'
SHOW_MS = 1500


def notify(title, body, replaces):
	import battery_watch
	return battery_watch.notify(title, body, 'input-mouse', replaces, SHOW_MS)


class Follower:
	"""One mouse: a thread that turns its 0x8100 events into notices."""

	def __init__(self, dev, name, send=notify):
		self.dev, self.name, self.send = dev, name, send
		self.mouse = mouse.Mouse(dev, name)
		self.shown = 0
		self.stop_event = threading.Event()
		self.thread = threading.Thread(target=self._run, daemon=True)

	def start(self):
		self.thread.start()

	def stop(self):
		self.stop_event.set()

	def _run(self):
		index = self.dev.feature_index(mouse.ONBOARD)
		rates = self.dev.feature_index(mouse.EXTENDED_RATE)
		try:
			while not self.stop_event.is_set():
				event = self.dev.next_event(1.0)
				if not event:
					continue
				if index and event[0] == index and event[1] in (PROFILE_ACTIVATED, DPI_CHANGED):
					self.handle(event[1])
				elif rates and event[0] == rates and event[1] == 0:
					self.handle(RATE_CHANGED, event[2][1])
		except (OSError, hidpp.HidppError):
			pass                       # unplugged
		finally:
			self.dev.close()

	def handle(self, kind, value=None):
		if not store.load_config().get('osd_notifications', True):
			return
		if kind == RATE_CHANGED:
			rates = mouse.EXTENDED_RATES
			hz = rates[value] if value < len(rates) else value
			title = f'{hz} Hz' if hz < 1000 else f'{hz / 1000:g} kHz'
			self.shown = self.send(title, self.name, self.shown)
			return
		profile = self.mouse.current_profile()
		if kind == PROFILE_ACTIVATED:
			title = f'Profile {profile}'
		else:
			title = f'{self.dpi(profile)} DPI'
		self.shown = self.send(title, self.name, self.shown)

	def dpi(self, profile):
		slot = self.mouse.current_dpi_slot()
		if not self.mouse.profiles:
			self.mouse.load_profiles()
		p = next((p for p in self.mouse.profiles if p.number == profile), None)
		levels = p.dpi_levels if p else []
		return levels[slot] if slot < len(levels) and levels[slot] else f'Level {slot + 1}'


class Watch:
	"""Used by the engine: follows the onboard mice that are connected."""
	CHECK_EVERY = 10.0

	def __init__(self):
		self.followers = {}        # device id -> Follower
		self.last = 0.0

	def due(self, now):
		return now - self.last >= self.CHECK_EVERY

	def check(self, now):
		import devices
		self.last = now
		for dev_id in [i for i, f in self.followers.items() if not f.thread.is_alive()]:
			del self.followers[dev_id]
		for d in devices.discover():
			if d.model.type != 'mouse' or d.id in self.followers:
				continue
			try:
				dev = devices.open_hidpp(d)
				if not (dev.has(mouse.ONBOARD) or dev.has(mouse.EXTENDED_RATE)):
					dev.close()
					continue
				f = Follower(dev, d.name)
			except (OSError, hidpp.HidppError):
				continue
			self.followers[d.id] = f
			f.start()

	def stop(self):
		for f in self.followers.values():
			f.stop()
