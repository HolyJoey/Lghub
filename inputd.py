"""Buttons and G-keys handled in software, the way G HUB does it, for buttons that run a macro.

Mice (HID++ 0x8110 MouseButtonSpy): read the device's remap table (function 3), start spying
(function 1), and set the entry of every button that runs a macro to 0 (function 4): such a
button no longer clicks by itself and is reported in a 16-bit big-endian event instead; all
other buttons keep working natively. Stopping restores the table and stops spying (function 2).

Keyboards (HID++ 0x8010 G-keys): software control on (function 2, 1), G-keys reported as a bit
mask (G1 = bit 0 of the first byte), off again when done.

assignments.json: {device ident: {"button:N" or "gkey:N": macro id}}, N counted from 1.
"""
import threading

import hidpp
import macros

SPY, GKEY = 0x8110, 0x8010


def ident(device):
	return f'{device.model.key}:{device.serial}' if device.serial else f'{device.model.key}:{device.id}'


class DeviceInput:
	"""One device's software buttons, on its own thread."""

	def __init__(self, dev, assigned, runner):
		self.dev = dev
		self.assigned = assigned          # {"button:N" / "gkey:N": macro}
		self.runner = runner
		self.stop_event = threading.Event()
		self.original_remap = None
		self.kind = None
		self.held = 0
		self.thread = None

	def start(self):
		if self.dev.has(SPY) and any(k.startswith('button:') for k in self.assigned):
			self.kind = SPY
			self.original_remap = self.dev.call(SPY, 3)[:16]
			self.dev.call(SPY, 1)
			remap = bytearray(self.original_remap)
			for key in self.assigned:
				n = int(key.split(':')[1])
				if key.startswith('button:') and 1 <= n <= 16:
					remap[n - 1] = 0          # handled here, not by the mouse
			self.dev.call(SPY, 4, bytes(remap))
		elif self.dev.has(GKEY) and any(k.startswith('gkey:') for k in self.assigned):
			self.kind = GKEY
			self.dev.call(GKEY, 2, b'\x01')
		else:
			return False
		self.thread = threading.Thread(target=self._run, daemon=True)
		self.thread.start()
		return True

	def stop(self):
		self.stop_event.set()
		if self.thread:
			self.thread.join(2)
		try:
			if self.kind == SPY:
				if self.original_remap is not None:
					self.dev.call(SPY, 4, self.original_remap)
				self.dev.call(SPY, 2)
			elif self.kind == GKEY:
				self.dev.call(GKEY, 2, b'\x00')
		except hidpp.HidppError:
			pass   # unplugged: nothing to restore

	def _run(self):
		index = self.dev.feature_index(self.kind)
		while not self.stop_event.is_set():
			try:
				event = self.dev.next_event(0.5)
			except OSError:
				return   # the device went away
			if not event or event[0] != index or event[1] != 0:
				continue
			p = event[2]
			if self.kind == SPY:
				self._changed('button', (p[0] << 8) | p[1])
			else:
				self._changed('gkey', int.from_bytes(p[:4], 'little'))

	def _changed(self, prefix, mask):
		diff = mask ^ self.held
		self.held = mask
		bit = 0
		while diff:
			if diff & 1:
				key = f'{prefix}:{bit + 1}'
				macro = self.assigned.get(key)
				if macro:
					(self.runner.press if mask >> bit & 1 else self.runner.release)(key, macro)
			diff >>= 1
			bit += 1


class DeviceActions:
	"""G HUB's DPI and profile macro actions on the mouse whose button ran them (ours: how they
	are carried out). With onboard memory on, DPI steps through the active profile's DPI slots
	and profile actions switch onboard profiles (0x8100); in host mode the DPI is set directly
	(0x2201) from the active profile's levels. DPI shift holds the profile's shift DPI while
	the button is down."""

	def __init__(self, dev):
		import mouse
		self.mouse = mouse.Mouse(dev, 'actions')
		self.onboard = self.mouse.onboard
		self.levels = []
		self.default = self.shift = 0
		self.before_shift = None
		self.lock = threading.Lock()

	def _profile(self):
		"""The active profile's DPI levels, default and shift slots (read when first needed)."""
		if self.onboard and not self.levels:
			number = self.mouse.current_profile()
			profiles = self.mouse.load_profiles()
			profile = next((p for p in profiles if p.number == number), profiles[0] if profiles else None)
			if profile:
				self.levels = [v for v in profile.dpi_levels if v]
				self.default, self.shift = profile.default_dpi, profile.shift_dpi
		return self.levels

	def __call__(self, kind, action, down=True):
		with self.lock:
			try:
				self._do(action, down)
			except (OSError, hidpp.HidppError) as e:
				print(f'engine: {action} failed: {e}', flush=True)

	def _do(self, action, down):
		if action.startswith('PROFILE_'):
			if down and self.onboard:
				self._profile_step(action)
			return
		levels = self._profile()
		if not levels:
			return
		if action == 'DPI_SHIFT':
			self._shift(levels, down)
			return
		if not down:
			return
		slot = self._current_slot(levels)
		target = {'DPI_UP': min(slot + 1, len(levels) - 1), 'DPI_DOWN': max(slot - 1, 0),
		          'DPI_CYCLE': (slot + 1) % len(levels), 'DPI_DEFAULT': min(self.default, len(levels) - 1)}.get(action)
		if target is not None:
			self._set_slot(levels, target)

	def _current_slot(self, levels):
		if self.onboard and self.mouse.mode() == 1:
			return min(self.mouse.current_dpi_slot(), len(levels) - 1)
		dpi = self.mouse.current_dpi()
		return min(range(len(levels)), key=lambda i: abs(levels[i] - dpi))

	def _set_slot(self, levels, slot):
		if self.onboard and self.mouse.mode() == 1:
			self.mouse.set_current_dpi_slot(slot)
		else:
			self.mouse.set_dpi(levels[slot])

	def _shift(self, levels, down):
		if down and self.before_shift is None:
			self.before_shift = self._current_slot(levels)
			self._set_slot(levels, min(self.shift, len(levels) - 1))
		elif not down and self.before_shift is not None:
			self._set_slot(levels, self.before_shift)
			self.before_shift = None

	def _profile_step(self, action):
		profiles = [p.number for p in self.mouse.load_profiles() if p.enabled] or [1]
		current = self.mouse.current_profile()
		i = profiles.index(current) if current in profiles else 0
		step = -1 if action == 'PROFILE_PREV' else 1
		if action == 'PROFILE_NEXT' and i == len(profiles) - 1 or action == 'PROFILE_PREV' and i == 0:
			return
		self.mouse.set_current_profile(profiles[(i + step) % len(profiles)])
		self.levels = []        # the new profile's DPI levels next time


def resolve(device_assignments, library):
	"""{"button:N": macro} from {"button:N": macro id}, skipping macros that no longer exist."""
	return {k: library[v] for k, v in device_assignments.items() if v in library}


def assigned_for(device):
	return resolve(macros.assignments().get(ident(device), {}), macros.library())


class Manager:
	"""Used by the engine: one DeviceInput per connected device that has macros on its buttons."""
	CHECK_EVERY = 60.0

	def __init__(self):
		import hotplug
		self.usb = hotplug.Watch(hotplug.USB)
		self.running = {}         # device id -> (DeviceInput, assigned)
		self.mtimes = None
		self.last_check = 0.0
		self.runner = None

	def due(self):
		import os
		import time
		mtimes = tuple(os.stat(p).st_mtime if os.path.exists(p) else None
		               for p in (macros.ASSIGNMENTS_FILE, macros.LIBRARY_FILE))
		changed = self.usb.changed() or mtimes != self.mtimes
		self.mtimes = mtimes
		return changed or time.monotonic() - self.last_check >= self.CHECK_EVERY

	def check(self):
		import time

		import devices
		self.last_check = time.monotonic()
		data = macros.assignments()
		if not data and not self.running:
			return
		lib = macros.library()
		found = {}
		for d in devices.discover():
			if d.model.type == 'receiver':
				try:
					for p in devices.scan_receiver(d):
						found[p.id] = p
				except OSError:
					continue
			else:
				found[d.id] = d
		for dev_id in list(self.running):
			d = found.get(dev_id)
			wanted = resolve(data.get(ident(d), {}), lib) if d else {}
			if wanted != self.running[dev_id][1]:
				self.running.pop(dev_id)[0].stop()
		for dev_id, d in found.items():
			wanted = resolve(data.get(ident(d), {}), lib)
			if not wanted or dev_id in self.running:
				continue
			try:
				dev = devices.open_hidpp(d)
				di = DeviceInput(dev, wanted, self._runner(dev, wanted))
				if di.start():
					self.running[dev_id] = (di, wanted)
					print(f'engine: software buttons on {d.name} ({len(wanted)} assigned)', flush=True)
			except (OSError, hidpp.HidppError) as e:
				print(f'engine: no software buttons on {d.name}: {e}', flush=True)

	def _runner(self, dev, wanted):
		"""The shared runner, or one of its own when the device has DPI/profile actions on it."""
		if any(macros.is_device_action(m) for m in wanted.values()):
			out = self.runner.out if self.runner else None
			return macros.Runner(out, DeviceActions(dev))
		if self.runner is None:
			self.runner = macros.Runner()
		return self.runner

	def stop(self):
		for di, _wanted in self.running.values():
			di.stop()
		self.running.clear()
