"""Headset pages besides Blue VO!CE: the equalizer and the headset's own controls."""
import threading

from gi.repository import GLib, Gtk

import eq
import headset
from hidpp_panel import SettingsPanel
from ui import NOTIFY_ACTIVE, box, label, page_header
from worker import Worker

SAVE_DELAY_MS = 150
REFRESH_SECONDS = 3


def switch_row(parent, title, hint, active, on_change):
	r = box(Gtk.Orientation.HORIZONTAL, 16)
	titles = box(spacing=2, hexpand=True)
	titles.append(label(title))
	if hint:
		titles.append(label(hint, ['muted', 'small'], wrap=True))
	r.append(titles)
	sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=active)
	sw.connect(NOTIFY_ACTIVE, lambda *_: on_change(sw.get_active()))
	r.append(sw)
	parent.append(r)
	return sw


class EqualizerPage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.settings = eq.load()
		self.loading = False
		self._save_id = 0
		self.append(page_header('Equalizer', '10-band EQ for everything you hear on the headset. Changes apply live.'))

		hero = box(Gtk.Orientation.HORIZONTAL, 20, ['card', 'hero'])
		left = box(spacing=6, hexpand=True)
		left.append(label('Equalizer', ['muted', 'small']))
		self.state_word = label('', ['big-word'])
		left.append(self.state_word)
		self.route = label('', ['muted', 'small'], wrap=True)
		left.append(self.route)
		hero.append(left)
		self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
		self.switch.connect(NOTIFY_ACTIVE, self._on_enable)
		hero.append(self.switch)
		self.append(hero)

		self.append(label('Presets', ['section-title']))
		self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10,
		                        min_children_per_line=2, max_children_per_line=7, homogeneous=True)
		self.preset_buttons = {}
		for name in eq.PRESETS:
			b = Gtk.Button(label=name)
			b.add_css_class('preset')
			b.set_size_request(-1, 44)
			b.connect('clicked', lambda _w, n=name: self._preset(n))
			self.flow.append(b)
			self.preset_buttons[name] = b
		self.append(self.flow)

		bands = box(Gtk.Orientation.HORIZONTAL, 6, ['card'], homogeneous=True)
		self.scales, self.values = [], []
		for i in range(len(eq.BANDS)):
			col = box(spacing=6)
			value = label('', ['value', 'small'], xalign=0.5)
			scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, -eq.RANGE, eq.RANGE, 0.5)
			scale.set_inverted(True)
			scale.set_draw_value(False)
			scale.set_size_request(-1, 220)
			scale.add_mark(0, Gtk.PositionType.RIGHT, None)
			scale.connect('value-changed', lambda w, i=i: self._on_band(i, w))
			col.append(value)
			col.append(scale)
			col.append(label(eq.band_label(i), ['muted', 'small'], xalign=0.5))
			bands.append(col)
			self.scales.append(scale)
			self.values.append(value)
		self.append(bands)

		out = box(spacing=12, css=['card'])
		out.append(label('Output', ['section-title']))
		out.append(label('Apps play into a new output, “… (Equalizer)”, which feeds the headset. Automatic follows '
		                 'the headset.', ['muted', 'small'], wrap=True))
		self.targets = [('auto', 'Automatic')]
		self.target_dd = Gtk.DropDown.new_from_strings([d for _, d in self.targets])
		self.target_dd.connect('notify::selected', self._on_target)
		out.append(self.target_dd)
		self.default_switch = switch_row(out, 'Use as default output', 'Apps that play to the system default go '
		                                 'through the equalizer.', self.settings['make_default'], self._on_default)
		self.append(out)
		self.load()

	def load(self):
		self.loading = True
		s = self.settings
		self.switch.set_active(s['enabled'])
		for i, g in enumerate(s['gains']):
			self.scales[i].set_value(g)
			self.values[i].set_text(f'{g:+.1f}')
		self.default_switch.set_active(s['make_default'])
		self.loading = False
		self._state()
		self.refresh_targets()

	def _state(self):
		s = self.settings
		self.state_word.set_text('On' if s['enabled'] else 'Off')
		self.route.set_text(f"Preset: {s['preset']}" if s['enabled'] else 'Sound goes to the headset unchanged.')
		for name, b in self.preset_buttons.items():
			(b.add_css_class if name == s['preset'] else b.remove_css_class)('selected')

	def refresh_targets(self):
		def work():
			found = eq.sinks()
			GLib.idle_add(lambda: self._fill_targets(found) and False)
		threading.Thread(target=work, daemon=True).start()

	def _fill_targets(self, found):
		wanted = self.settings.get('target', 'auto')
		targets = [('auto', 'Automatic')] + [(s['name'], s['description']) for s in found]
		if wanted != 'auto' and wanted not in [n for n, _ in targets]:
			targets.append((wanted, f'{wanted} (not connected)'))
		if targets == self.targets and self.target_dd.get_selected() != Gtk.INVALID_LIST_POSITION:
			return
		self.targets = targets
		self.loading = True
		self.target_dd.set_model(Gtk.StringList.new([d for _, d in targets]))
		self.target_dd.set_selected(next(i for i, (n, _) in enumerate(targets) if n == wanted))
		self.loading = False

	def _save_soon(self):
		self._state()
		if self._save_id:
			GLib.source_remove(self._save_id)
		self._save_id = GLib.timeout_add(SAVE_DELAY_MS, self._save_now)

	def _save_now(self):
		self._save_id = 0
		eq.save(self.settings)
		return False

	def _on_enable(self, *_):
		if not self.loading:
			self.settings['enabled'] = self.switch.get_active()
			self._save_soon()

	def _on_band(self, i, scale):
		g = round(scale.get_value() * 2) / 2
		self.values[i].set_text(f'{g:+.1f}')
		if self.loading:
			return
		self.settings['gains'][i] = g
		self.settings['preset'] = next((n for n, p in eq.PRESETS.items() if list(p) == self.settings['gains']),
		                               'Custom')
		self._save_soon()

	def _preset(self, name):
		self.settings['gains'] = [float(g) for g in eq.PRESETS[name]]
		self.settings['preset'] = name
		self.load()
		self._save_soon()

	def _on_target(self, *_):
		i = self.target_dd.get_selected()
		if self.loading or i == Gtk.INVALID_LIST_POSITION or i >= len(self.targets):
			return
		self.settings['target'] = self.targets[i][0]
		self._save_soon()

	def _on_default(self, on):
		if not self.loading:
			self.settings['make_default'] = on
			self._save_soon()


class HeadsetPage(Gtk.Box):
	"""Sidetone, volume and mic level from the headset's sound card, and, with hidpp, whatever
	the headset offers over HID++ (lighting, battery, sidetone)."""

	def __init__(self, win, hidpp=True):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.device = None
		self.use_hidpp = hidpp
		self.panel = None
		self.worker = Worker()
		self.card = None
		self.loading = False
		self._shown = None
		self.append(page_header('Headset', 'Sidetone (hearing your own voice), volume, microphone level and '
		                        'lighting, set in the headset itself.'))
		self.body = box(spacing=20)
		self.append(self.body)
		self.message = label('', ['muted'], wrap=True)
		self.body.append(self.message)
		self.extra = box(spacing=20)
		self.append(self.extra)

	def close(self):
		self.worker.stop()
		if self.panel:
			self.panel.close()

	def set_device(self, device):
		if device is self.device:
			return
		self.device = device
		self._shown = None
		if self.panel:
			self.panel.close()
			self.extra.remove(self.panel)
			self.panel = None
		if device and self.use_hidpp:
			self.panel = SettingsPanel(self.win, device, quiet=True)
			self.extra.append(self.panel)
		self.refresh()

	def refresh(self):
		device = self.device
		if not device:
			self._show_message('Plug in the headset to change its own settings.')
			return
		if device.wireless:
			self._show_message('')   # no sound card of its own: everything is over HID++ below
			return
		self.worker.submit(lambda: self._read(device), self._show)

	@staticmethod
	def _read(device):
		"""(sound card, its controls). On the worker thread."""
		card = headset.alsa_card(device.port)
		return card, headset.controls(card) if card is not None else []

	def _show_message(self, text):
		while (child := self.body.get_first_child()):
			self.body.remove(child)
		self.message.set_text(text)
		self.body.append(self.message)

	def _show(self, result):
		card, ctrls = result
		key = (card, [(c.name, c.index, c.percent, c.on) for c in ctrls])
		if key == self._shown:
			return
		self._shown = key
		self.card = card
		if card is None:
			self._show_message('This headset’s sound card wasn’t found. Is it plugged in directly (not through a hub '
			                   'that hides it)?')
			return
		while (child := self.body.get_first_child()):
			self.body.remove(child)
		self.loading = True
		side = [c for c in ctrls if c.is_sidetone]
		if side:
			self.body.append(self._sidetone_card(side))
		for title, group in (('Microphone', [c for c in ctrls if c.capture and not c.is_sidetone]),
		                     ('Volume', [c for c in ctrls if not c.capture and not c.is_sidetone])):
			if group:
				self.body.append(self._group_card(title, group))
		self.loading = False

	def _sidetone_card(self, controls):
		c = self._group_card('Sidetone', controls)
		c.insert_child_after(label('Hear your own voice in the headset, so you don’t talk louder than you mean to.',
		                           ['muted', 'small'], wrap=True), c.get_first_child())
		return c

	def _group_card(self, title, controls):
		c = box(spacing=12, css=['card'])
		c.append(label(title, ['section-title']))
		for ctrl in controls:
			self._control_rows(c, ctrl)
		return c

	def _slider(self, title, value, on_change):
		r = box(Gtk.Orientation.HORIZONTAL, 14)
		r.append(label(title, ['muted'], width_chars=18))
		scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
		scale.set_hexpand(True)
		scale.set_value(value)
		scale.set_draw_value(False)
		shown = label(f'{value:.0f} %', ['value'], width_chars=6, xalign=1.0)

		def changed(w):
			shown.set_text(f'{w.get_value():.0f} %')
			if not self.loading:
				on_change(w.get_value())
		scale.connect('value-changed', changed)
		r.append(scale)
		r.append(shown)
		return r

	def _control_rows(self, parent, ctrl):
		card = self.card

		def toggled(sw, *_):
			if not self.loading:
				on = sw.get_active()
				self.worker.submit(lambda: headset.set_switch(card, ctrl, on))
		sw = None
		if ctrl.has_switch:
			sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=bool(ctrl.on))
			sw.set_tooltip_text('Recording' if ctrl.capture else 'On')
			sw.connect(NOTIFY_ACTIVE, toggled)
		if ctrl.has_volume:
			r = self._slider(ctrl.name, ctrl.percent, lambda v: self.worker.submit(lambda: headset.set_volume(card, ctrl, v)))
		else:
			r = box(Gtk.Orientation.HORIZONTAL, 14)
			r.append(label(ctrl.name, ['muted'], hexpand=True))
		if sw:
			r.append(sw)
		parent.append(r)
