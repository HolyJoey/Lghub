"""The mouse page: DPI, report rate, buttons, lighting and onboard profiles.

Edits change a copy of the profile; "Save to mouse" writes it to the mouse's memory, where it
keeps working without Lghub running (like G HUB's on-board memory mode).
"""
from gi.repository import Gdk, Gtk

import devices
import features
import hidpp_panel
import macros_ui
import mouse
from ui import box, button_widget, device_icon, device_sidebar, label, nav_button, page_header, scrolled
from worker import Worker

PAGES = (('sensitivity', 'Sensitivity', 'input-mouse-symbolic'),
         ('buttons', 'Buttons', 'input-keyboard-symbolic'),
         ('lighting', 'Lighting', 'weather-clear-symbolic'),
         ('profiles', 'Profiles', 'view-list-symbolic'),
         ('macros', 'Macros', 'media-record-symbolic'))
BUTTON_NAMES = ('Left button', 'Right button', 'Middle button (wheel click)', 'Back', 'Forward')
ZONE_NAMES = {'primary': 'DPI indicator / main', 'branding': 'Logo'}
NOTIFY_SELECTED = 'notify::selected'

# GDK key names -> HID keyboard usage names in mouse.KEY_NAMES.
GDK_KEYS = {'Return': 'Enter', 'Escape': 'Esc', 'BackSpace': 'Backspace', 'Tab': 'Tab', 'space': 'Space',
            'minus': '-', 'equal': '=', 'bracketleft': '[', 'bracketright': ']', 'backslash': '\\',
            'semicolon': ';', 'apostrophe': "'", 'grave': '`', 'comma': ',', 'period': '.', 'slash': '/',
            'Caps_Lock': 'Caps Lock', 'Print': 'Print Screen', 'Scroll_Lock': 'Scroll Lock', 'Pause': 'Pause',
            'Insert': 'Insert', 'Home': 'Home', 'Prior': 'Page Up', 'Page_Up': 'Page Up', 'Delete': 'Delete',
            'End': 'End', 'Next': 'Page Down', 'Page_Down': 'Page Down', 'Right': 'Right', 'Left': 'Left',
            'Down': 'Down', 'Up': 'Up', 'Menu': 'Menu'}
HID_BY_NAME = {name: usage for usage, name in mouse.KEY_NAMES.items()}
MODIFIER_KEYS = {'Control_L', 'Control_R', 'Shift_L', 'Shift_R', 'Alt_L', 'Alt_R', 'Super_L', 'Super_R',
                 'ISO_Level3_Shift', 'Meta_L', 'Meta_R'}


def hid_usage(keyval):
	name = Gdk.keyval_name(keyval) or ''
	if len(name) == 1 and name.isalnum():
		name = name.upper()
	return HID_BY_NAME.get(GDK_KEYS.get(name, name))


def hid_modifiers(state):
	bits = 0
	for mask, bit in ((Gdk.ModifierType.CONTROL_MASK, 0x01), (Gdk.ModifierType.SHIFT_MASK, 0x02),
	                  (Gdk.ModifierType.ALT_MASK, 0x04), (Gdk.ModifierType.SUPER_MASK, 0x08)):
		if state & mask:
			bits |= bit
	return bits


def card(title=None, hint=None, spacing=12):
	c = box(spacing=spacing, css=['card'])
	if title:
		c.append(label(title, ['section-title']))
	if hint:
		c.append(label(hint, ['muted', 'small'], wrap=True))
	return c


def row(title, widget, hint=None):
	r = box(Gtk.Orientation.HORIZONTAL, 16)
	titles = box(spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
	titles.append(label(title))
	if hint:
		titles.append(label(hint, ['muted', 'small'], wrap=True))
	r.append(titles)
	widget.set_valign(Gtk.Align.CENTER)
	r.append(widget)
	return r


def clear(container):
	while (child := container.get_first_child()):
		container.remove(child)


class MouseView(Gtk.Box):
	def __init__(self, win, device):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
		self.win = win
		self.device = device
		self.mouse = None
		self.profiles = []
		self.editing = 0          # index into self.profiles
		self.active = None        # the mouse's current profile number
		self.loading = False
		self.worker = Worker()

		icon = device_icon(device, 32)
		side = device_sidebar(win.show_home, icon, device.name, device.type_name)
		nav = box(spacing=4)
		self.nav_buttons = {}
		for key, text, icon_name in PAGES:
			b = nav_button(text, icon_name, lambda k=key: self.show_page(k))
			nav.append(b)
			self.nav_buttons[key] = b
		side.append(nav)
		side.append(box(vexpand=True))
		self.side_card = card(spacing=6)
		self.side_card.append(label('Active profile', ['muted', 'small']))
		self.side_profile = label('—', ['big-word'], wrap=True)
		self.side_card.append(self.side_profile)
		self.side_detail = label('', ['muted', 'small'], wrap=True, max_width_chars=24)
		self.side_card.append(self.side_detail)
		side.append(self.side_card)
		self.append(side)

		right = box(hexpand=True)
		self.save_bar = box(Gtk.Orientation.HORIZONTAL, 12, ['card', 'hero'])
		self.save_bar.set_margin_start(40)
		self.save_bar.set_margin_end(40)
		self.save_bar.set_margin_top(16)
		self.save_bar.append(label('Unsaved changes.', hexpand=True, valign=Gtk.Align.CENTER))
		self.save_bar.append(button_widget('Discard', ['ghost'], self._discard))
		self.save_bar.append(button_widget('Save to mouse', ['apply'], self._save))
		self.save_bar.set_visible(False)
		right.append(self.save_bar)
		self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
		self.pages = {}
		for key, _text, _icon in PAGES:
			if key == 'macros':
				page = macros_ui.MacrosPage(win, device, [(f'button:{i + 1}', BUTTON_NAMES[i] if i < len(BUTTON_NAMES)
				                                           else f'Button {i + 1}') for i in range(1, 11)])
				# not the left button: the mouse must always keep a primary click
			else:
				page = box(spacing=20, css=['page'])
			self.pages[key] = page
			self.stack.add_named(scrolled(page), key)
		message = box(spacing=12, css=['page'])
		self.message = label('Connecting to the mouse…', ['muted'], wrap=True)
		message.append(page_header(device.name, device.type_name))
		message.append(self.message)
		self.stack.add_named(message, 'message')
		right.append(self.stack)
		self.append(right)
		self.stack.set_visible_child_name('message')
		self.current_page = 'sensitivity'
		self._mark_nav(None)
		self.worker.submit(self._connect, self._connected, self._failed)

	def close(self):
		self.worker.stop()

	# --- device ---------------------------------------------------------------------------

	def _connect(self):
		m = mouse.Mouse(devices.open_hidpp(self.device), self.device.serial or self.device.id)
		state = {'battery': features.battery(m.dev), 'wheel': m.wheel()}
		if features.BUTTON_SWAP in m.features:
			state['swap'] = features.button_swap(m.dev)
		if features.HYBRID_TRACKING in m.features:
			state['hybrid'] = features.hybrid_mode(m.dev)
		if features.BUNNY_HOPPING in m.features:
			state['bhop'] = features.bunny_hopping(m.dev)
		if m.onboard:
			m.load_profiles()
			state['mode'] = m.mode()
			state['active'] = m.current_profile()
			state['slot'] = m.current_dpi_slot()
		else:
			state['dpi'] = m.current_dpi() if m.sensor else None
			if features.COLOR_LED_EFFECTS in m.features:
				state['zones'] = features.zones(m.dev)
			elif features.RGB_EFFECTS in m.features:
				state['zones'] = features.zones_v2(m.dev)
			state['rate'] = m.current_rate() if m.rates else None
		return m, state

	def _connected(self, result):
		self.mouse, state = result
		self.state = state
		self.profiles = self.mouse.profiles
		self.active = state.get('active')
		numbers = [p.number for p in self.profiles]
		self.editing = numbers.index(self.active) if self.active in numbers else 0
		self.rebuild()
		self.show_page(self.current_page)

	def _failed(self, error):
		self.stack.set_visible_child_name('message')
		self._mark_nav(None)
		self.message.set_text(f'Can’t talk to the mouse: {error}.\n\nCheck that the udev rule is installed '
		                      '(/etc/udev/rules.d/70-lghub.rules, run ./install.sh) and replug the mouse.')

	def show_page(self, key):
		self.current_page = key
		if self.mouse is None:
			return
		self.stack.set_visible_child_name(key)
		self._mark_nav(key)

	def _mark_nav(self, key):
		for k, b in self.nav_buttons.items():
			(b.add_css_class if k == key else b.remove_css_class)('active')
			b.set_sensitive(self.mouse is not None)

	@property
	def profile(self):
		return self.profiles[self.editing] if self.profiles else None

	def changed(self):
		if not self.loading:
			self.save_bar.set_visible(any(p.dirty for p in self.profiles))

	def rebuild(self):
		self.loading = True
		self._build_sensitivity()
		self._build_buttons()
		self._build_lighting()
		self._build_profiles()
		self._side()
		self.loading = False
		self.changed()

	def _side(self):
		battery = self.state.get('battery')
		power = ''
		if battery:
			percent, text = battery
			power = ' · '.join(filter(None, (f'Battery {percent} %' if percent is not None else '', text))) + '\n'
		if not self.mouse.onboard:
			self.side_profile.set_text('Live')
			self.side_detail.set_text(power + 'This mouse has no onboard memory; settings apply until it is '
			                          'switched off.')
			return
		active = next((p for p in self.profiles if p.number == self.active), None)
		self.side_profile.set_text(active.name if active else '—')
		mode = 'On-board memory' if self.state.get('mode') == mouse.MODE_ONBOARD else 'Software mode'
		self.side_detail.set_text(power + (f'{mode} · {self.mouse.firmware}' if self.mouse.firmware else mode))

	def _profile_picker(self, page):
		"""'Editing: <profile>' at the top of the pages that edit a profile."""
		names = [p.name + (' (active)' if p.number == self.active else '') for p in self.profiles]
		dd = Gtk.DropDown.new_from_strings(names)
		dd.set_selected(self.editing)

		def pick(*_):
			if not self.loading and dd.get_selected() < len(self.profiles):
				self.editing = dd.get_selected()
				self.rebuild()
		dd.connect(NOTIFY_SELECTED, pick)
		r = box(Gtk.Orientation.HORIZONTAL, 10)
		r.append(label('Editing', ['muted'], valign=Gtk.Align.CENTER))
		r.append(dd)
		page.append(r)

	# --- sensitivity ----------------------------------------------------------------------

	def _build_sensitivity(self):
		page = self.pages['sensitivity']
		clear(page)
		page.append(page_header('Sensitivity', 'DPI levels and how often the mouse reports to the computer.'))
		if not self.mouse.onboard:
			self._live_sensitivity(page)
			self._wheel_card(page)
			self._bhop_card(page)
			self._tracking_card(page)
			return
		self._profile_picker(page)
		p = self.profile
		sensor = self.mouse.sensor or mouse.Sensor()
		c = card('DPI levels', 'Switch between them with the DPI buttons. The default is where the mouse starts; '
		         'the shift level is used while you hold DPI Shift.')
		group = None
		levels = p.dpi_levels
		for slot in range(mouse.DPI_SLOTS):
			r = box(Gtk.Orientation.HORIZONTAL, 14)
			check = Gtk.CheckButton(label=f'Level {slot + 1}', group=group, active=slot == p.default_dpi)
			check.set_tooltip_text('Default level')
			group = group or check
			check.connect('toggled', lambda w, s=slot: w.get_active() and self._set_default_dpi(s))
			check.set_size_request(110, -1)
			r.append(check)
			on = Gtk.Switch(active=bool(levels[slot]), valign=Gtk.Align.CENTER)
			adj = Gtk.Adjustment(value=levels[slot] or 800, lower=sensor.low, upper=sensor.high,
			                     step_increment=sensor.step, page_increment=sensor.step * 10)
			scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj, hexpand=True,
			                  draw_value=False, sensitive=bool(levels[slot]))
			spin = Gtk.SpinButton(adjustment=adj, numeric=True, width_chars=6, sensitive=bool(levels[slot]))
			adj.connect('value-changed', lambda a, s=slot, sw=on: self._set_dpi(s, a, sw))
			on.connect('notify::active', lambda w, _p, s=slot, a=adj, sc=scale, sp=spin: self._toggle_dpi(s, w, a, sc, sp))
			check.set_sensitive(bool(levels[slot]))
			r.append(scale)
			r.append(spin)
			r.append(on)
			if slot == 0:
				on.set_sensitive(False)   # a profile needs at least one level
			c.append(r)
		page.append(c)

		c = card('DPI shift', 'Hold the DPI Shift button (on the G502, the thumb button in front) for this level.')
		used = [s for s in range(mouse.DPI_SLOTS) if levels[s]]
		dd = Gtk.DropDown.new_from_strings([f'Level {s + 1} · {levels[s]} DPI' for s in used])
		dd.set_selected(used.index(p.shift_dpi) if p.shift_dpi in used else 0)
		dd.connect(NOTIFY_SELECTED, lambda w, _p: self._edit(lambda: setattr(p, 'shift_dpi', used[w.get_selected()])))
		c.append(row('Shift level', dd))
		page.append(c)

		c = card('Report rate', 'Higher is smoother and uses a little more CPU.')
		rates = self.mouse.rates or [1000, 500, 250, 125]
		dd = Gtk.DropDown.new_from_strings([f'{r} Hz ({1000 / r:g} ms)' for r in rates])
		dd.set_selected(rates.index(p.report_rate) if p.report_rate in rates else 0)
		dd.connect(NOTIFY_SELECTED, lambda w, _p: self._edit(lambda: setattr(p, 'report_rate', rates[w.get_selected()])))
		c.append(row('Reports per second', dd))
		page.append(c)
		self._wheel_card(page)
		self._bhop_card(page)
		self._tracking_card(page)

	def _edit(self, change):
		if self.loading:
			return
		change()
		self.changed()

	def _set_default_dpi(self, slot):
		self._edit(lambda: setattr(self.profile, 'default_dpi', slot))

	def _set_dpi(self, slot, adj, switch):
		if self.loading or not switch.get_active():
			return
		sensor = self.mouse.sensor or mouse.Sensor()
		value = sensor.clamp(adj.get_value())
		self._edit(lambda: self.profile.set_dpi(slot, value))

	def _toggle_dpi(self, slot, switch, adj, scale, spin):
		on = switch.get_active()
		scale.set_sensitive(on)
		spin.set_sensitive(on)
		if self.loading:
			return
		sensor = self.mouse.sensor or mouse.Sensor()
		self._edit(lambda: self.profile.set_dpi(slot, sensor.clamp(adj.get_value()) if on else 0))
		if not on and self.profile.default_dpi == slot:
			self.profile.default_dpi = 0
		self.rebuild()

	def _live_sensitivity(self, page):
		sensor = self.mouse.sensor
		if sensor:
			c = card('DPI', 'Applies right away, until the mouse is unplugged.')
			adj = Gtk.Adjustment(value=self.state.get('dpi') or 800, lower=sensor.low, upper=sensor.high,
			                     step_increment=sensor.step, page_increment=sensor.step * 10)
			scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj, hexpand=True, draw_value=False)
			spin = Gtk.SpinButton(adjustment=adj, numeric=True, width_chars=6)
			r = box(Gtk.Orientation.HORIZONTAL, 14)
			r.append(scale)
			r.append(spin)
			c.append(r)
			adj.connect('value-changed', lambda a: self._live(lambda: self.mouse.set_dpi(sensor.clamp(a.get_value()))))
			page.append(c)
		if self.mouse.rates:
			c = card('Report rate')
			rates = self.mouse.rates
			dd = Gtk.DropDown.new_from_strings([f'{r} Hz' for r in rates])
			current = self.state.get('rate')
			dd.set_selected(rates.index(current) if current in rates else 0)
			dd.connect(NOTIFY_SELECTED, lambda w, _p: self._live(lambda: self.mouse.set_rate(rates[w.get_selected()])))
			c.append(row('Reports per second', dd))
			page.append(c)

	def _tracking_card(self, page):
		if 'swap' not in self.state and self.state.get('hybrid') is None:
			return
		c = card('Buttons and tracking')
		if 'swap' in self.state:
			sw = Gtk.Switch(active=self.state['swap'], valign=Gtk.Align.CENTER)
			sw.connect('notify::active', lambda w, _p: self._live(
				lambda on=w.get_active(): features.set_button_swap(self.mouse.dev, on)))
			c.append(row('Left-handed (swap the main buttons)', sw))
		if self.state.get('hybrid') is not None:
			modes = features.HYBRID_MODES
			dd = Gtk.DropDown.new_from_strings([name for _v, name in modes])
			dd.set_selected(next(i for i, (v, _n) in enumerate(modes) if v == self.state['hybrid']))
			dd.connect(NOTIFY_SELECTED, lambda w, _p: self._live(
				lambda mode=modes[w.get_selected()][0]: features.set_hybrid_mode(self.mouse.dev, mode)))
			c.append(row('Hybrid tracking', dd))
		page.append(c)

	def _bhop_card(self, page):
		if 'bhop' not in self.state:
			return
		ms = self.state['bhop']
		c = card('Bunny hopping', 'Keeps the scroll wheel repeating for a while after you flick it.')
		sw = Gtk.Switch(active=ms > 0, valign=Gtk.Align.CENTER)
		scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, features.BHOP_MIN, features.BHOP_MAX,
		                                 features.BHOP_STEP)
		scale.set_value(min(max(ms, features.BHOP_MIN), features.BHOP_MAX) if ms else 500)
		scale.set_size_request(280, -1)
		scale.set_draw_value(True)
		scale.set_format_value_func(lambda _s, v: f'{round(v / 100) * 100:.0f} ms')
		scale.set_sensitive(ms > 0)

		def apply(*_):
			scale.set_sensitive(sw.get_active())
			value = round(scale.get_value() / 100) * 100 if sw.get_active() else 0
			self._live(lambda: features.set_bunny_hopping(self.mouse.dev, value))

		sw.connect('notify::active', apply)
		scale.connect('value-changed', apply)
		c.append(row('Bunny hopping', sw))
		c.append(row('Timeout', scale))
		page.append(c)

	def _wheel_card(self, page):
		w = self.state.get('wheel')
		if not w:
			return
		c = card('Scroll wheel', 'Ratchet clicks, or free spin. SmartShift lets a ratcheting wheel spin free when you '
		         'flick it; the threshold is the speed for that (the mouse’s own scale).')
		mode = Gtk.DropDown.new_from_strings(['Ratchet', 'Free spin'])
		mode.set_selected(1 if w['mode'] == mouse.FREE_SPIN else 0)
		smart = Gtk.Switch(active=w['auto'] not in (0, mouse.ALWAYS_RATCHET), valign=Gtk.Align.CENTER)
		auto = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 4, 50, 1)   # range ours; 4 = G HUB's lowest
		auto.set_value(w['auto'] if 4 <= w['auto'] < mouse.ALWAYS_RATCHET else 10)
		auto.set_size_request(280, -1)
		torque = None
		if w['max_torque']:
			torque = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, w['max_torque'], 1)
			torque.set_value(w['torque'] or 1)
			torque.set_size_request(280, -1)

		def apply(*_):
			self._apply_wheel(mode, smart, auto, torque)

		mode.connect(NOTIFY_SELECTED, apply)
		smart.connect('notify::active', apply)
		auto.connect('value-changed', apply)
		c.append(row('Wheel', mode))
		c.append(row('SmartShift', smart))
		c.append(row('Threshold', auto))
		if torque:
			torque.connect('value-changed', apply)
			c.append(row('Ratchet force', torque))
		self.loading = True
		auto.set_sensitive(w['mode'] != mouse.FREE_SPIN and smart.get_active())
		smart.set_sensitive(w['mode'] != mouse.FREE_SPIN)
		self.loading = False
		page.append(c)

	def _apply_wheel(self, mode, smart, auto, torque):
		free = mode.get_selected() == 1
		auto.set_sensitive(not free and smart.get_active())
		smart.set_sensitive(not free)
		if free:
			args = (mouse.FREE_SPIN, 0)
		else:
			args = (mouse.RATCHET, int(auto.get_value()) if smart.get_active() else mouse.ALWAYS_RATCHET)
		force = int(torque.get_value()) if torque else None
		self._live(lambda: self.mouse.set_wheel(*args, force))

	def _live(self, job):
		if not self.loading:
			self.worker.submit(job, None, lambda e: self.win.toast(f'The mouse refused: {e}'))

	# --- buttons --------------------------------------------------------------------------

	def _build_buttons(self):
		page = self.pages['buttons']
		clear(page)
		page.append(page_header('Buttons', 'What each button does. G-Shift: a second layer while you hold the '
		                        'button set to G-Shift.'))
		if not self.mouse.onboard:
			page.append(label('This mouse has no onboard memory, so its buttons can’t be changed here.', ['muted']))
			return
		self._profile_picker(page)
		for shifted in (False, True):
			c = card('G-Shift layer' if shifted else 'Buttons')
			for i in range(self.mouse.button_count or mouse.BUTTON_SLOTS):
				c.append(self._button_row(i, shifted))
			page.append(c)

	def _button_row(self, i, shifted):
		p = self.profile
		action = p.button(i, shifted)
		current = action.describe()
		names = [name for name, _a in mouse.PRESET_ACTIONS]
		choices = names + ['Keystroke…']
		if current not in names:
			choices.insert(0, current)
		dd = Gtk.DropDown.new_from_strings(choices)
		dd.set_selected(choices.index(current) if current in choices else 0)

		def pick(w, _p):
			if self.loading:
				return
			choice = choices[w.get_selected()]
			if choice == 'Keystroke…':
				self._record_key(i, shifted)
				return
			preset = dict(mouse.PRESET_ACTIONS).get(choice)
			if preset:
				self._edit(lambda: p.set_button(i, preset, shifted))
		dd.connect(NOTIFY_SELECTED, pick)
		name = BUTTON_NAMES[i] if i < len(BUTTON_NAMES) else f'Button {i + 1}'
		return row(name, dd)

	def _record_key(self, i, shifted):
		dialog = Gtk.Window(title='Record a keystroke', modal=True, transient_for=self.get_root(),
		                    default_width=380, default_height=160)
		content = box(spacing=12, css=['page'])
		content.append(label('Press the key (with Ctrl, Shift, Alt or Super if you like).', wrap=True))
		shown = label('…', ['big-word'])
		content.append(shown)
		dialog.set_child(content)
		keys = Gtk.EventControllerKey()

		def pressed(_c, keyval, _code, state):
			name = Gdk.keyval_name(keyval) or ''
			usage = hid_usage(keyval)
			if name in MODIFIER_KEYS:
				pass                       # wait for the key that goes with them
			elif usage is None:
				shown.set_text(f'{name}: not supported')
			else:
				action = mouse.Action.key(hid_modifiers(state), usage)
				self._edit(lambda: self.profile.set_button(i, action, shifted))
				dialog.close()
				self.rebuild()
			return True                    # every key press is ours while recording
		keys.connect('key-pressed', pressed)
		dialog.add_controller(keys)
		dialog.connect('close-request', lambda *_: self.rebuild() and False)
		dialog.present()

	# --- lighting -------------------------------------------------------------------------

	def _build_lighting(self):
		page = self.pages['lighting']
		clear(page)
		page.append(page_header('Lighting', 'Effects stored in the profile, so they run without the computer.'
		                        if self.mouse.onboard else 'Applies right away, until the mouse is switched off.'))
		if not self.mouse.onboard:
			zones = self.state.get('zones') or []
			if not zones:
				page.append(label('This mouse has no lighting Lghub can set.', ['muted']))
			for zone in zones:
				page.append(hidpp_panel.zone_card(zone, lambda: self.loading, self._live, lambda: self.mouse.dev))
			return
		zones = self.device.model.lighting
		if not zones and self.device.model.key != 'unknown':
			page.append(label('This model has no lighting.', ['muted']))
			return
		self._profile_picker(page)
		for i, zone in enumerate((zones or ('primary', 'branding'))[:mouse.LED_SLOTS]):
			page.append(self._led_card(i, ZONE_NAMES.get(zone, zone.replace('_', ' ').capitalize())))

	def _led_card(self, i, title):
		p = self.profile
		led = p.led(i)
		c = card(title)
		effects = list(mouse.LED_EFFECTS)
		effect_dd = Gtk.DropDown.new_from_strings([mouse.LED_EFFECTS[e] for e in effects])
		effect_dd.set_selected(effects.index(led.effect) if led.effect in effects else 0)
		c.append(row('Effect', effect_dd))
		color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
		rgba = Gdk.RGBA()
		rgba.red, rgba.green, rgba.blue, rgba.alpha = (*(v / 255 for v in led.color), 1.0)
		color.set_rgba(rgba)
		color_row = row('Color', color)
		c.append(color_row)
		speed = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 20, 0.5)
		speed.set_value(led.period / 1000)
		speed.set_size_request(260, -1)
		speed.set_draw_value(True)
		speed_row = row('Speed (seconds per cycle)', speed)
		c.append(speed_row)
		bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
		bright.set_value(led.brightness)
		bright.set_size_request(260, -1)
		bright.set_draw_value(True)
		bright_row = row('Brightness (%)', bright)
		c.append(bright_row)

		def visible():
			effect = effects[effect_dd.get_selected()]
			color_row.set_visible(effect in (mouse.LED_FIXED, mouse.LED_BREATHING))
			speed_row.set_visible(effect in (mouse.LED_CYCLE, mouse.LED_BREATHING))
			bright_row.set_visible(effect in (mouse.LED_CYCLE, mouse.LED_BREATHING))

		def apply(*_):
			visible()
			rgb = color.get_rgba()
			new = mouse.Led.build(effects[effect_dd.get_selected()],
			                      tuple(round(v * 255) for v in (rgb.red, rgb.green, rgb.blue)),
			                      speed.get_value() * 1000, bright.get_value())
			self._edit(lambda: p.set_led(i, new))
		effect_dd.connect(NOTIFY_SELECTED, apply)
		color.connect('notify::rgba', apply)
		speed.connect('value-changed', apply)
		bright.connect('value-changed', apply)
		visible()
		return c

	# --- profiles -------------------------------------------------------------------------

	def _build_profiles(self):
		page = self.pages['profiles']
		clear(page)
		page.append(page_header('Profiles', 'Profiles live in the mouse. The profile button switches between '
		                        'the enabled ones.'))
		if not self.mouse.onboard:
			page.append(label('This mouse has no onboard memory.', ['muted']))
			return
		if self.state.get('mode') != mouse.MODE_ONBOARD:
			c = card('Software mode', 'The mouse is waiting for software to drive it, so its stored profiles are '
			         'ignored. Lghub uses on-board memory.')
			c.append(button_widget('Use on-board memory', ['apply'], self._use_onboard))
			page.append(c)
		if not self.mouse.directory_valid:
			page.append(label('The mouse is running its factory profiles. Saving copies them to its memory first.',
			                  ['muted', 'small'], wrap=True))
		for idx, p in enumerate(self.profiles):
			c = card(spacing=10)
			head = box(Gtk.Orientation.HORIZONTAL, 12)
			entry = Gtk.Entry(text=p.name, hexpand=True, max_length=mouse.NAME_BYTES // 2 - 1)
			entry.connect('changed', lambda w, q=p: self._rename(q, w.get_text()))
			head.append(entry)
			if p.number == self.active:
				head.append(label('Active', ['ok'], valign=Gtk.Align.CENTER))
			else:
				head.append(button_widget('Activate', ['ghost'], lambda n=p.number: self._activate(n)))
			head.append(button_widget('Edit', ['ghost'], lambda i=idx: self._edit_profile(i)))
			c.append(head)
			levels = ', '.join(str(v) for v in p.dpi_levels if v)
			c.append(label(f'{levels} DPI · {p.report_rate} Hz', ['muted', 'small']))
			page.append(c)

	def _rename(self, p, text):
		if self.loading or not text.strip():
			return
		self.editing = self.profiles.index(p)
		self._edit(lambda: setattr(p, 'name', text.strip()))

	def _edit_profile(self, i):
		self.editing = i
		self.rebuild()
		self.show_page('sensitivity')

	def _activate(self, number):
		def job():
			self.mouse.set_current_profile(number)
			return number

		def done(n):
			self.active = n
			self.rebuild()
			self.win.toast('Profile switched')
		self.worker.submit(job, done, lambda e: self.win.toast(f'Couldn’t switch: {e}'))

	def _use_onboard(self):
		def job():
			self.mouse.set_mode(mouse.MODE_ONBOARD)
			return self.mouse.mode()

		def done(mode):
			self.state['mode'] = mode
			self.rebuild()
		self.worker.submit(job, done, lambda e: self.win.toast(f'The mouse refused: {e}'))

	# --- save -----------------------------------------------------------------------------

	def _save(self):
		self.save_bar.set_sensitive(False)
		profiles = self.profiles
		active = self.active

		def job():
			self.mouse.save(profiles)
			if active:
				self.mouse.set_current_profile(active)   # reload what the mouse runs now
			return True

		def done(_ok):
			self.save_bar.set_sensitive(True)
			self.rebuild()
			self.win.toast('Saved to the mouse')

		def failed(e):
			self.save_bar.set_sensitive(True)
			self.win.toast(f'Saving failed: {e}')
		self.worker.submit(job, done, failed)

	def _discard(self):
		for p in self.profiles:
			p.revert()
		self.rebuild()
