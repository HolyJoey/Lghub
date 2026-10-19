"""Device settings over HID++: lighting zones, brightness, report rate, sidetone, onboard
memory and battery, built from what the device says it has. Changes apply right away. Used on
the generic device page and on the headset page."""
from gi.repository import Gdk, Gtk

import devices
import features
import headset
import mouse
import perkey
import perkey_ui
from ui import box, label
from worker import Worker

NOTIFY_SELECTED = 'notify::selected'


def card(title, hint=None):
	c = box(spacing=12, css=['card'])
	c.append(label(title, ['section-title']))
	if hint:
		c.append(label(hint, ['muted', 'small'], wrap=True))
	return c


def row(title, widget):
	r = box(Gtk.Orientation.HORIZONTAL, 16)
	r.append(label(title, ['muted'], hexpand=True, valign=Gtk.Align.CENTER))
	widget.set_valign(Gtk.Align.CENTER)
	r.append(widget)
	return r


def slider(low, high, value, width=280):
	s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, 1)
	s.set_value(value)
	s.set_draw_value(True)
	s.set_size_request(width, -1)
	return s


class SettingsPanel(Gtk.Box):
	"""on_status(title, detail) gets the device's own name and its battery/firmware line.
	quiet: show nothing at all when the device doesn't speak HID++ (for pages that have other
	settings anyway)."""

	def __init__(self, win, device, on_status=None, quiet=False):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20)
		self.win = win
		self.device = device
		self.on_status = on_status or (lambda _title, _detail: None)
		self.quiet = quiet
		self.dev = None
		self.loading = False
		self.worker = Worker()
		self.body = self
		if not quiet:
			self.append(label('Asking the device what it can do…', ['muted']))
		self.worker.submit(self._connect, self._connected, self._no_hidpp)

	def close(self):
		self.worker.stop()

	def apply_perkey(self, colors):
		"""Per-key colours ({"group:id": [r, g, b]}) to the device, if it has per-key lighting."""
		dev = self.dev
		if dev is not None:
			self._do(lambda: perkey.apply(dev, colors))

	# --- talking to the device ------------------------------------------------------------

	def _connect(self):
		dev = devices.open_hidpp(self.device)
		info = {'features': dev.feature_list(), 'name': dev.name(), 'firmware': dev.firmware(),
		        'battery': features.battery(dev)}
		have = info['features']
		if features.COLOR_LED_EFFECTS in have:
			info['zones'] = features.zones(dev)
		if features.BRIGHTNESS in have:
			info['brightness'] = features.brightness(dev)
		if features.REPORT_RATE in have:
			mask = dev.call(features.REPORT_RATE, 0)[0]
			info['rates'] = sorted((1000 // (bit + 1) for bit in range(8) if mask >> bit & 1), reverse=True)
			ms = dev.call(features.REPORT_RATE, 1)[0]
			info['rate'] = 1000 // ms if ms else 0
		if features.SIDETONE in have:
			info['sidetone'] = headset.sidetone(dev)
		if features.ONBOARD in have:
			info['mode'] = dev.call(features.ONBOARD, 2)[0]
		saved = perkey_ui.load_colors(self.device.model.key)
		if perkey.PERKEY in have and saved:
			perkey.apply(dev, saved)   # ours: the saved colours go back on when the keyboard connects
		self.dev = dev
		return info

	def _do(self, job, done=None):
		self.worker.submit(job, done, lambda e: self.win.toast(f'The device refused: {e}'))

	def _no_hidpp(self, error):
		self._clear()
		if self.quiet:
			return
		self.on_status('Connected', 'No HID++ settings')
		facts = []
		model = self.device.model
		if model.lighting:
			facts.append('lighting')
		if 'onboard' in model.flags:
			facts.append('onboard memory')
		text = f'Lghub can’t change this device’s own settings ({error}).'
		if facts:
			text += ' G HUB lists ' + ' and '.join(facts) + ' for this model.'
		self.body.append(label(text, ['muted'], wrap=True))

	def _clear(self):
		while (child := self.body.get_first_child()):
			self.body.remove(child)

	def _connected(self, info):
		self._clear()
		self.loading = True
		self.on_status(info['name'] or self.device.name, self._status_text(info))
		cards = [self._zone_card(zone) for zone in info.get('zones', [])]
		for key, build in (('brightness', self._brightness_card), ('rates', self._rate_card),
		                   ('sidetone', self._sidetone_card), ('mode', self._mode_card)):
			if info.get(key) not in (None, []):
				cards.append(build(info))
		if not cards and not self.quiet:
			self.body.append(label('This device has no settings Lghub can change yet.', ['muted'], wrap=True))
		for c in cards + ([] if self.quiet else [self._features_card(info)]):
			self.body.append(c)
		self.loading = False

	@staticmethod
	def _status_text(info):
		lines = []
		if info['battery']:
			percent, text = info['battery']
			lines.append(' · '.join(filter(None, (f'Battery {percent} %' if percent is not None else '', text))))
		if info['firmware']:
			lines.append(f'Firmware {info["firmware"]}')
		return '\n'.join(lines)

	def _brightness_card(self, info):
		value, high = info['brightness']
		c = card('Brightness')
		s = slider(0, high, value)
		s.connect('value-changed', lambda w: self.loading or self._do(
			lambda v=int(w.get_value()): features.set_brightness(self.dev, v)))
		c.append(row('Lighting brightness', s))
		return c

	def _rate_card(self, info):
		c = card('Report rate', 'How often the device reports to the computer.')
		rates = info['rates']
		dd = Gtk.DropDown.new_from_strings([f'{r} Hz' for r in rates])
		dd.set_selected(rates.index(info['rate']) if info['rate'] in rates else 0)
		dd.connect(NOTIFY_SELECTED, lambda w, _p: self.loading or self._do(
			lambda r=rates[w.get_selected()]: self.dev.call(features.REPORT_RATE, 2, bytes([round(1000 / r)]))))
		c.append(row('Reports per second', dd))
		return c

	def _sidetone_card(self, info):
		c = card('Sidetone', 'Hear your own voice in the headset.')
		s = slider(0, 100, info['sidetone'])
		s.connect('value-changed', lambda w: self.loading or self._do(
			lambda v=int(w.get_value()): headset.set_sidetone(self.dev, v)))
		c.append(row('Level', s))
		return c

	def _mode_card(self, info):
		c = card('On-board memory', 'On: the device runs the settings stored in it. Off: it follows software; '
		         'lighting changes here may need this off on some keyboards.')
		sw = Gtk.Switch(active=info['mode'] == mouse.MODE_ONBOARD)
		sw.connect('notify::active', lambda w, _p: self.loading or self._do(
			lambda on=w.get_active(): self.dev.call(features.ONBOARD, 1,
			                                        bytes([mouse.MODE_ONBOARD if on else mouse.MODE_HOST]))))
		c.append(row('Use on-board memory', sw))
		return c

	@staticmethod
	def _features_card(info):
		c = card('What it reports')
		flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, column_spacing=6,
		                   row_spacing=6)
		names = sorted({features.NAMES.get(f, f'0x{f:04X}') for f in info['features']
		                if f not in (0x0000, 0x0001, 0x0002)})
		for name in names:
			flow.append(label(name, ['chip']))
		c.append(flow)
		return c

	def _zone_card(self, zone):
		c = card(f'Lighting · {zone.name}')
		effects = [(i, eid) for i, eid in zone.effects]
		names = [features.EFFECTS.get(eid, f'Effect 0x{eid:04X}') for _i, eid in effects]
		effect_dd = Gtk.DropDown.new_from_strings(names)
		c.append(row('Effect', effect_dd))
		color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
		rgba = Gdk.RGBA()
		rgba.parse('#2f8cff')
		color.set_rgba(rgba)
		color_row = row('Color', color)
		c.append(color_row)
		speed = slider(1, 20, 3)
		speed_row = row('Speed (seconds per cycle)', speed)
		c.append(speed_row)
		bright = slider(1, 100, 100)
		bright_row = row('Brightness (%)', bright)
		c.append(bright_row)

		def visible():
			eid = effects[effect_dd.get_selected()][1]
			color_row.set_visible(eid in features.NEEDS_COLOR)
			speed_row.set_visible(eid in features.NEEDS_SPEED)
			bright_row.set_visible(eid in features.NEEDS_SPEED)

		def apply(*_):
			visible()
			if self.loading:
				return
			index, eid = effects[effect_dd.get_selected()]
			rgb = color.get_rgba()
			params = features.effect_params(eid, tuple(round(v * 255) for v in (rgb.red, rgb.green, rgb.blue)),
			                                speed.get_value() * 1000, bright.get_value())
			self._do(lambda: features.set_effect(self.dev, zone.index, index, params))
		effect_dd.connect(NOTIFY_SELECTED, apply)
		color.connect('notify::rgba', apply)
		speed.connect('value-changed', apply)
		bright.connect('value-changed', apply)
		visible()
		return c
