"""The page for keyboards, headsets, speakers and anything else: built from what the device
says it can do over HID++ (lighting, brightness, report rate, sidetone, onboard memory,
battery), plus the controls of its USB sound card if it has one. Changes apply right away."""
from gi.repository import Gdk, Gtk

import devices
import features
import headset
import headset_ui
import mouse
from ui import box, device_icon, device_sidebar, label, nav_button, page_header, scrolled
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


class GenericView(Gtk.Box):
	def __init__(self, win, device):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
		self.win = win
		self.device = device
		self.dev = None
		self.worker = Worker()
		self.loading = False

		icon = device_icon(device, 32)
		side = device_sidebar(win.show_home, icon, device.name, device.type_name)
		self.nav = box(spacing=4)
		self.nav_buttons = {}
		side.append(self.nav)
		side.append(box(vexpand=True))
		self.side_card = box(spacing=6, css=['card'])
		self.side_title = label('Connecting…', ['muted', 'small'], wrap=True, max_width_chars=24)
		self.side_card.append(self.side_title)
		self.side_detail = label('', ['small'], wrap=True, max_width_chars=24)
		self.side_card.append(self.side_detail)
		side.append(self.side_card)
		self.append(side)

		self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True)
		self.page = box(spacing=20, css=['page'])
		self.page.append(page_header(device.name, f'{device.type_name}'
		                             + (' · wireless' if device.wireless else ' · connected over USB')))
		self.body = box(spacing=20)
		self.body.append(label('Asking the device what it can do…', ['muted']))
		self.page.append(self.body)
		self.stack.add_named(scrolled(self.page), 'settings')
		self._add_nav('settings', 'Settings', 'emblem-system-symbolic')
		self.audio = None
		if not device.wireless and headset.alsa_card(device.port) is not None:
			self.audio = headset_ui.HeadsetPage(win)
			self.stack.add_named(scrolled(self.audio), 'audio')
			self._add_nav('audio', 'Sound', 'audio-volume-high-symbolic')
			self.audio.set_device(device)
		self.append(self.stack)
		self.show_page('settings')
		self.worker.submit(self._connect, self._connected, self._no_hidpp)

	def close(self):
		self.worker.stop()
		if self.audio:
			self.audio.worker.stop()

	def _add_nav(self, key, text, icon):
		b = nav_button(text, icon, lambda: self.show_page(key))
		self.nav.append(b)
		self.nav_buttons[key] = b

	def show_page(self, key):
		self.stack.set_visible_child_name(key)
		for k, b in self.nav_buttons.items():
			(b.add_css_class if k == key else b.remove_css_class)('active')
		if key == 'audio' and self.audio:
			self.audio.refresh()

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
		self.dev = dev
		return info

	def _do(self, job, done=None):
		self.worker.submit(job, done, lambda e: self.win.toast(f'The device refused: {e}'))

	def _no_hidpp(self, error):
		self.side_title.set_text('Connected')
		self.side_detail.set_text('No HID++ settings')
		self._clear()
		facts = []
		model = self.device.model
		if model.lighting:
			facts.append('lighting')
		if 'onboard' in model.flags:
			facts.append('onboard memory')
		text = ('Lghub can’t change this device’s own settings yet' + (f' ({error})' if self.audio is None else '')
		        + '.')
		if facts:
			text += ' G HUB lists ' + ' and '.join(facts) + ' for this model.'
		if self.audio:
			text += ' Its sound settings are on the Sound page.'
		self.body.append(label(text, ['muted'], wrap=True))

	def _clear(self):
		while (child := self.body.get_first_child()):
			self.body.remove(child)

	def _connected(self, info):
		self._clear()
		self.loading = True
		self.side_title.set_text(info['name'] or self.device.name)
		detail = []
		if info['battery']:
			percent, text = info['battery']
			detail.append(' · '.join(filter(None, (f'Battery {percent} %' if percent is not None else '', text))))
		if info['firmware']:
			detail.append(f'Firmware {info["firmware"]}')
		self.side_detail.set_text('\n'.join(detail))

		for zone in info.get('zones', []):
			self.body.append(self._zone_card(zone))
		if 'brightness' in info:
			value, high = info['brightness']
			c = card('Brightness')
			s = slider(0, high, value)
			s.connect('value-changed', lambda w: self.loading or self._do(
				lambda v=int(w.get_value()): features.set_brightness(self.dev, v)))
			c.append(row('Lighting brightness', s))
			self.body.append(c)
		if info.get('rates'):
			c = card('Report rate', 'How often the device reports to the computer.')
			rates = info['rates']
			dd = Gtk.DropDown.new_from_strings([f'{r} Hz' for r in rates])
			dd.set_selected(rates.index(info['rate']) if info['rate'] in rates else 0)
			dd.connect(NOTIFY_SELECTED, lambda w, _p: self.loading or self._do(
				lambda r=rates[w.get_selected()]: self.dev.call(features.REPORT_RATE, 2, bytes([round(1000 / r)]))))
			c.append(row('Reports per second', dd))
			self.body.append(c)
		if 'sidetone' in info:
			c = card('Sidetone', 'Hear your own voice in the headset.')
			s = slider(0, 100, info['sidetone'])
			s.connect('value-changed', lambda w: self.loading or self._do(
				lambda v=int(w.get_value()): headset.set_sidetone(self.dev, v)))
			c.append(row('Level', s))
			self.body.append(c)
		if 'mode' in info:
			c = card('On-board memory', 'On: the device runs the settings stored in it. Off: it follows software; '
			         'lighting changes here may need this off on some keyboards.')
			sw = Gtk.Switch(active=info['mode'] == mouse.MODE_ONBOARD)
			sw.connect('notify::active', lambda w, _p: self.loading or self._do(
				lambda on=w.get_active(): self.dev.call(features.ONBOARD, 1,
				                                        bytes([mouse.MODE_ONBOARD if on else mouse.MODE_HOST]))))
			c.append(row('Use on-board memory', sw))
			self.body.append(c)

		c = card('What it reports')
		chips = box(Gtk.Orientation.HORIZONTAL, 6)
		flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, column_spacing=6,
		                   row_spacing=6)
		names = sorted({features.NAMES.get(f, f'0x{f:04X}') for f in info['features']
		                if f not in (0x0000, 0x0001, 0x0002)})
		for name in names:
			flow.append(label(name, ['chip']))
		chips.append(flow)
		c.append(chips)
		self.body.append(c)
		if not any(k in info for k in ('zones', 'brightness', 'rates', 'sidetone', 'mode')):
			self.body.prepend(label('This device has no settings Lghub can change yet.', ['muted'], wrap=True))
		self.loading = False

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
