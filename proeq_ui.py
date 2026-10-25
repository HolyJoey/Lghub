"""The G Pro X's PRO equalizer card: G HUB's 5 bands (+-12 dB) on the headset's own chip, per
profile, with G HUB's band maths (proeq.py)."""
from gi.repository import GLib, Gtk

import proeq
from ui import box, label

DEBOUNCE_MS = 300               # ours: one write when a slider stops moving


class ProEqCard(Gtk.Box):
	def __init__(self, device, worker):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, css_classes=['card'])
		self.device, self.worker = device, worker
		self.loading = False
		self.pending = {}
		self.append(label('PRO equalizer', ['section-title']))
		self.append(label('The equalizer built into the headset (G HUB’s five bands, ±12 dB). It stays on the '
		                  'headset, so it works on any computer or console.', ['muted', 'small'], wrap=True))
		self.body = box(spacing=10)
		self.append(self.body)
		self.body.append(label('Reading the headset…', ['muted']))
		self.worker.submit(self._read, self._show, self._failed)

	def _chip(self):
		found = proeq.find(self.device.port)
		if not found:
			raise OSError('no equalizer interface on this headset')
		return proeq.Chip(*found)

	def _read(self, profile=None):
		chip = self._chip()
		try:
			if profile is not None:
				chip.set_profile(profile)
			current = chip.profile()
			return current, chip.bands(current)
		finally:
			chip.close()

	def _clear(self):
		while (child := self.body.get_first_child()):
			self.body.remove(child)

	def _failed(self, error):
		self._clear()
		self.body.append(label(f'Lghub can’t read the headset’s equalizer ({error}).', ['muted'], wrap=True))

	def _show(self, result):
		profile, bands = result
		self._clear()
		self.loading = True
		names = [f'Profile {i + 1}' for i in range(4)]
		dd = Gtk.DropDown.new_from_strings(names)
		dd.set_selected(profile)
		dd.connect('notify::selected', lambda w, _p: self.loading or self.worker.submit(
			lambda: self._read(w.get_selected()), self._show, self._failed))
		r = box(Gtk.Orientation.HORIZONTAL, 14)
		r.append(label('Profile', ['muted'], hexpand=True))
		r.append(dd)
		self.body.append(r)
		for i, (kind, freq, _q, gain) in enumerate(bands):
			self.body.append(self._band(profile, i + 1, kind, freq, gain))
		self.loading = False

	def _band(self, profile, band, kind, freq, gain):
		r = box(Gtk.Orientation.HORIZONTAL, 14)
		hz = f'{freq / 1000:g} kHz' if freq >= 1000 else f'{freq} Hz'
		r.append(label(f'{hz} ({proeq.TYPES.get(kind, kind)})', ['muted'], width_chars=22))
		scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -proeq.MAX_GAIN_DB, proeq.MAX_GAIN_DB, 0.5)
		scale.set_hexpand(True)
		scale.set_value(gain)
		scale.set_draw_value(False)
		shown = label(f'{gain:+.1f} dB', ['value'], width_chars=8, xalign=1.0)

		def changed(w):
			shown.set_text(f'{w.get_value():+.1f} dB')
			if not self.loading:
				self._later(profile, band, w.get_value())
		scale.connect('value-changed', changed)
		r.append(scale)
		r.append(shown)
		return r

	def _later(self, profile, band, gain):
		old = self.pending.pop(band, None)
		if old:
			GLib.source_remove(old)

		def send():
			self.pending.pop(band, None)
			self.worker.submit(lambda: self._set(profile, band, gain), None, self._failed)
			return False
		self.pending[band] = GLib.timeout_add(DEBOUNCE_MS, send)

	def _set(self, profile, band, gain):
		chip = self._chip()
		try:
			chip.set_band_gain(profile, band, gain)
		finally:
			chip.close()
