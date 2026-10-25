"""Device settings over HID++: lighting zones, brightness, report rate, sidetone, onboard
memory and battery, built from what the device says it has. Changes apply right away. Used on
the generic device page and on the headset page."""
from gi.repository import Gdk, GLib, Gtk

import devices
import analog_keys
import battery_model
import centurion_eq
import device_settings
import features
import headset
import hidpp
import lightsync_ui
import mouse
import perkey
import perkey_ui
import store
from ui import box, label
from worker import Worker

NOTIFY_SELECTED = 'notify::selected'
NOTIFY_ACTIVE = 'notify::active'


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


# Features read the same way on connect: (feature, info key, reader)
SIMPLE_READS = ((features.SIDETONE, 'sidetone', headset.sidetone),
                (headset.CENTURION_SIDETONE, 'sidetone', headset.sidetone),
                (headset.CENTURION_ANC, 'anc', lambda dev: (headset.anc_mode(dev), *headset.anc_button(dev))),
                (centurion_eq.EQ, 'onboard_eq', centurion_eq.read),
                (headset.MIC_SELECT, 'mic_select', headset.mics),
                (headset.AUX_CONFIG, 'aux', headset.aux_mode),
                (headset.USB_PORTS, 'usb_ports', headset.usb_ports),
                (features.POLAR_PATTERN, 'patterns', features.polar_patterns),
                (features.DEVICE_EQ, 'device_eq', features.device_eq),
                (features.ANGLE_SNAPPING, 'angle_snapping', features.angle_snapping),
                (features.CHARGING_CONTROL, 'charging', features.charging),
                (features.BASS_TONE, 'bass_tone', features.bass_tone))

def _plural(n, word):
	return f'{n} {word}' + ('' if n == 1 else 's')


def analog_summary(a):
	"""Lines describing an analog profile (device_settings.analog_profile), read from the keyboard."""
	lines = []
	if 'actuation' in a:
		line = f'Actuation point {a["actuation"]:.2f} mm'
		if a.get('keys'):
			line += f', {_plural(len(a["keys"]), "key")} with their own'
		lines.append(line)
	if a.get('rapid'):
		lines.append(f'Rapid-trigger sensitivity set on {_plural(len(a["rapid"]), "key")}')
	if a.get('pairs'):
		kinds = sorted({str(p[2]) for p in a['pairs']})
		lines.append(f'{_plural(len(a["pairs"]), "key-priority pair")} ({", ".join(kinds)})')
	if lines:
		lines.append('Read from the keyboard’s onboard profile. Changing them stays off until it is checked on a '
		             'keyboard (a wrong write would overwrite a profile).')
	return lines


def report_rates(dev):
	"""(rates the device offers in Hz, highest first; the current one) from 0x8060."""
	mask = dev.call(features.REPORT_RATE, 0)[0]
	rates = sorted((1000 // (bit + 1) for bit in range(8) if mask >> bit & 1), reverse=True)
	ms = dev.call(features.REPORT_RATE, 1)[0]
	return rates, 1000 // ms if ms else 0


def slider(low, high, value, width=280):
	s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, 1)
	s.set_value(value)
	s.set_draw_value(True)
	s.set_size_request(width, -1)
	return s


def _minutes_text(m):
	if not m:
		return 'Never'
	return '1 minute' if m == 1 else f'{m} minutes'


def power_card(timers, do, dev, card=card, row=row):
	"""Power saving and power off timers (0x8103 tags 1 and 2) with G HUB's choices; a value not
	in the list is added, as G HUB does. card / row: the page's own builders."""
	c = card('Power', 'When the device goes into power saving, and when it turns itself off.')
	for tag, title, choices in ((device_settings.POWER_SAVING, 'Power saving after', device_settings.POWER_SAVING_MINUTES),
	                            (device_settings.POWER_OFF, 'Turn off after', device_settings.POWER_OFF_MINUTES)):
		if tag not in timers:
			continue
		current = round(timers[tag] / 60)
		minutes = sorted(set(choices) | {current})
		dd = Gtk.DropDown.new_from_strings([_minutes_text(m) for m in minutes])
		dd.set_selected(minutes.index(current))
		dd.connect(NOTIFY_SELECTED, lambda w, _p, t=tag, ms=minutes: do(
			lambda m=ms[w.get_selected()]: device_settings.set_timeout(dev, t, m * 60)))
		c.append(row(title, dd))
	return c


def _config_switch(key):
	sw = Gtk.Switch(active=store.load_config().get(key, True), valign=Gtk.Align.CENTER)

	def changed(w, _p):
		cfg = store.load_config()
		cfg[key] = w.get_active()
		store.save_config(cfg)

	sw.connect(NOTIFY_ACTIVE, changed)
	return sw


def battery_warnings_card(card=card, row=row, battery=True, osd=False):
	"""Switches for G HUB's desktop notifications (all devices, as G HUB's settings): low battery
	(30 % and 15 %), and a mouse's DPI and profile changes."""
	c = card('Notifications', 'Desktop notifications from the background service.')
	if battery:
		c.append(row('Warn when the battery is low (30 %, 15 %)', _config_switch('battery_warnings')))
	if osd:
		c.append(row('Show DPI, profile and report rate changes', _config_switch('osd_notifications')))
	return c


def zone_card(zone, loading, do, dev):
	"""A lighting zone's effect, colour, speed and brightness (0x8070 / 0x8071), applied live."""
	c = card(f'Lighting · {zone.name}')
	effects = [(i, eid) for i, eid in zone.effects]
	names = [features.EFFECTS.get(eid, f'Effect 0x{eid:04X}') for _i, eid in effects]
	effect_dd = Gtk.DropDown.new_from_strings(names)
	c.append(row('Effect', effect_dd))
	def color_button(hex_):
		button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
		rgba = Gdk.RGBA()
		rgba.parse(hex_)
		button.set_rgba(rgba)
		return button
	color, color2 = color_button('#2f8cff'), color_button('#ff00ab')
	color_row = row('Color', color)
	c.append(color_row)
	color2_row = row('Second color', color2)
	c.append(color2_row)
	direction = Gtk.DropDown.new_from_strings(list(features.DIRECTIONS.values()))
	direction_row = row('Direction', direction)
	c.append(direction_row)
	style = Gtk.DropDown.new_from_strings(list(features.STYLES.values()))
	style_row = row('Style', style)
	c.append(style_row)
	speed = slider(1, 20, 3)
	speed_row = row('Speed (seconds per cycle)', speed)
	c.append(speed_row)
	bright = slider(1, 100, 100)
	bright_row = row('Brightness (%)', bright)
	c.append(bright_row)

	def visible():
		eid = effects[effect_dd.get_selected()][1]
		color_row.set_visible(eid in features.NEEDS_COLOR)
		color2_row.set_visible(eid in features.NEEDS_COLOR2)
		direction_row.set_visible(eid == features.COLOR_WAVE)
		style_row.set_visible(eid in features.SIGNATURE_STYLES)
		speed_row.set_visible(eid in features.NEEDS_SPEED)
		bright_row.set_visible(eid in features.NEEDS_BRIGHTNESS)

	def apply(*_):
		visible()
		if loading():
			return
		index, eid = effects[effect_dd.get_selected()]
		def rgb(button):
			c = button.get_rgba()
			return tuple(round(v * 255) for v in (c.red, c.green, c.blue))
		params = features.effect_params(eid, rgb(color), speed.get_value() * 1000, bright.get_value(), rgb(color2),
		                                list(features.DIRECTIONS)[direction.get_selected()],
		                                list(features.STYLES)[style.get_selected()])
		do(lambda: features.set_effect(dev(), zone.index, index, params, feature=zone.feature))
	effect_dd.connect(NOTIFY_SELECTED, apply)
	color.connect('notify::rgba', apply)
	color2.connect('notify::rgba', apply)
	direction.connect(NOTIFY_SELECTED, apply)
	style.connect(NOTIFY_SELECTED, apply)
	speed.connect('value-changed', apply)
	bright.connect('value-changed', apply)
	visible()
	return c


class SettingsPanel(Gtk.Box):
	"""on_status(title, detail) gets the device's own name and its battery/firmware line.
	quiet: show nothing at all when the device doesn't speak HID++ (for pages that have other
	settings anyway), only why a headset has no sidetone unless set_sidetone_elsewhere(True)."""

	def __init__(self, win, device, on_status=None, quiet=False):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20)
		self.win = win
		self.device = device
		self.on_status = on_status or (lambda _title, _detail: None)
		self.quiet = quiet
		self.dev = None
		self.host = 0               # Easy-Switch host the device is on (Fn inversion is per host)
		self.loading = False
		self.worker = Worker()
		self.body = self
		self.no_sidetone = None     # the "why no sidetone" card, hidden when the sound card has one
		self.sidetone_elsewhere = False
		if not quiet:
			self.append(label('Asking the device what it can do…', ['muted']))
		self.worker.submit(self._connect, self._connected, self._no_hidpp)

	def close(self):
		self.worker.stop()

	def set_sidetone_elsewhere(self, elsewhere):
		self.sidetone_elsewhere = elsewhere
		if self.no_sidetone:
			self.no_sidetone.set_visible(not elsewhere)

	def apply_perkey(self, colors):
		"""Per-key colours ({"group:id": [r, g, b]}) to the device, if it has per-key lighting."""
		dev = self.dev
		if dev is not None:
			light_map = perkey.load_light_map(self.device.model.key)

			def send():
				if not dev.has(perkey.PERKEY) and dev.has(perkey.HOST_MODE):     # a newer headset (0x0620)
					dev.call(perkey.HOST_MODE, perkey.HM_SET_STATE, bytes([1]))
					perkey.apply_host_mode(dev, colors, persist=True, light_map=light_map)
				else:
					perkey.apply(dev, colors, light_map=light_map)
			self._do(send)

	# --- talking to the device ------------------------------------------------------------

	def _connect(self):
		dev = devices.open_hidpp(self.device)
		info = {'features': dev.feature_list(), 'name': dev.name(), 'firmware': dev.firmware(),
		        'battery': features.battery(dev, self._curves(dev))}
		have = info['features']
		if features.COLOR_LED_EFFECTS in have:
			info['zones'] = features.zones(dev)
		elif features.RGB_EFFECTS in have:
			info['zones'] = features.zones_v2(dev)
		if features.BRIGHTNESS in have:
			info['brightness'] = features.brightness(dev)
		if features.REPORT_RATE in have:
			info['rates'], info['rate'] = report_rates(dev)
		for feature, key, read in SIMPLE_READS:
			if feature in have:
				info[key] = read(dev)
		self._read_keyboard(dev, have, info)
		if features.ILLUMINATION in have:
			info['light'] = features.illumination(dev)
		info['life'] = battery_model.life_for(self.device, info['battery'], info.get('rate'))
		self._read_mic(dev, have, info)
		if any(f in have for f in headset.SWITCHES):
			info['headset_switches'] = headset.switches(dev)
		if device_settings.GLOBAL_SETTINGS in have:
			info['power'] = device_settings.power_timers(dev) or None
		if features.ONBOARD in have:
			info['mode'] = dev.call(features.ONBOARD, 2)[0]
			info['profiles'] = (dev.call(features.ONBOARD, 0)[3], dev.call(features.ONBOARD, 4)[1])
		saved = perkey_ui.load_colors(self.device.model.key)
		if (perkey.PERKEY in have or perkey.PERKEY_V1 in have) and saved:
			perkey.apply(dev, saved, light_map=perkey.load_light_map(self.device.model.key))   # ours: the saved colours go back on when the keyboard connects
		self.dev = dev
		return info

	def _curves(self, dev):
		"""G HUB's voltage curves, only for devices that report volts."""
		if dev.has(features.BATTERY_VOLTAGE) or dev.has(features.ADC_MEASUREMENT):
			return battery_model.for_device(self.device)
		return None

	def _read_mic(self, dev, have, info):
		"""The Yeti's own mute, gain, headphone level and mic monitoring (0x8370 / 0x8360 / 0x8350)."""
		mic = features.mic_gain_adjust(dev, self.device.usb_id) if features.MIC_GAIN_ADJUST in have else {}
		for feature, key, read in ((features.HEADPHONE_ADJUST, 'headphones', features.headphone_level),
		                           (features.MIC_BLEND, 'monitoring', features.mic_monitoring)):
			level = read(dev) if feature in have else None
			if level is not None:
				mic[key] = level
		if headset.CENTURION_MIC_MUTE in have:            # the newer headsets' own features
			mic['muted'], mic['centurion'] = headset.centurion_mic_muted(dev), True
		if headset.CENTURION_MIC_GAIN in have:
			gain, low, high = headset.centurion_mic_gain(dev)
			if high > low:
				mic['gain'], mic['gain_range'], mic['centurion'] = gain, (low, high), True
		if features.JACK_DETECTION in have:
			plugged = features.headphones_plugged(dev)
			if plugged is not None:
				mic['plugged'] = plugged
		if mic:
			info['mic'] = mic

	def _read_keyboard(self, dev, have, info):
		"""Easy-Switch hosts, Fn keys (per host) and game mode."""
		host = 0
		if features.CHANGE_HOST in have:
			info['hosts'] = features.hosts(dev)
			host = info['hosts'][1]
			if features.HOSTS_INFO in have:
				info['host_names'] = [features.host_name(dev, h) for h in range(info['hosts'][0])]
		if features.FN_INVERSION in have:
			info['fn_inversion'] = features.fn_inversion(dev, host)
			self.host = host
		if features.ANALOG_KEYS in have:
			info['analog'] = features.analog_switches(dev)
			if device_settings.PROFILE_MANAGEMENT in have:
				try:
					info['analog_profile'] = device_settings.analog_profile(dev, device_settings.active_profile(dev))
					if features.CONTROL_LIST in have:
						info['analog_cids'] = features.control_list(dev)
				except (OSError, hidpp.HidppError, IndexError):
					pass
		if features.DISABLE_KEYS in have or features.DISABLE_KEYS_V1 in have:
			most, keys = features.game_mode_choices(dev)
			info['game_mode'] = (most, features.game_mode_keys(self.device.model.key), keys)
			features.apply_game_mode(dev, info['game_mode'][1])   # ours: the chosen keys stay off

	def _do(self, job, done=None):
		self.worker.submit(job, done, lambda e: self.win.toast(f'The device refused: {e}'))

	def _no_hidpp(self, error):
		self._clear()
		if self.quiet:
			if self.device.model.type == 'headset':
				self.body.append(self._no_sidetone_card(f'its HID++ connection didn’t answer ({error})'))
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
		if info.get('zones') and not (perkey.PERKEY in info['features'] or perkey.PERKEY_V1 in info['features']):
			cards.append(lightsync_ui.card(self.device.model.key, lambda: None, per_key=False))
		for key, build in (('brightness', self._brightness_card), ('rates', self._rate_card),
		                   ('sidetone', self._sidetone_card), ('patterns', self._pattern_card),
		                   ('angle_snapping', self._angle_card), ('fn_inversion', self._fn_card),
		                   ('analog', self._analog_card), ('light', self._light_card),
		                   ('game_mode', self._game_mode_card), ('hosts', self._hosts_card),
		                   ('device_eq', self._device_eq_card), ('charging', self._charging_card),
		                   ('bass_tone', self._bass_card), ('mic', self._mic_card), ('anc', self._anc_card),
		                   ('onboard_eq', self._onboard_eq_card), ('headset_switches', self._switches_card),
		                   ('mic_select', self._mic_select_card), ('aux', self._aux_card),
		                   ('usb_ports', self._usb_ports_card),
		                   ('power', lambda i: power_card(i['power'], self._do, self.dev)),
		                   ('battery', lambda _i: battery_warnings_card()),
		                   ('mode', self._mode_card)):
			if info.get(key) not in (None, []) or key in ('charging', 'bass_tone') and key in info:
				cards.append(build(info))
		if self.device.model.type == 'headset' and 'sidetone' not in info:
			cards.append(self._no_sidetone_card('it doesn’t report a sidetone setting over HID++'))
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
			lines.append(' · '.join(filter(None, (f'Battery {percent} %' if percent is not None else '', text,
			                                      info.get('life')))))
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

	def _light_card(self, info):
		light = info['light']
		c = card('Light', 'The Litra’s own settings, as G HUB sets them.')
		sw = Gtk.Switch(active=light['on'], valign=Gtk.Align.CENTER)
		sw.connect(NOTIFY_ACTIVE, lambda w, _p: self.loading or self._do(
			lambda on=w.get_active(): features.set_illumination(self.dev, on)))
		c.append(row('On', sw))
		for key, title, unit, setter in (('brightness', 'Brightness', ' lm', features.set_light_brightness),
		                                 ('temperature', 'Colour temperature', ' K', features.set_color_temperature)):
			low, high, step = light[key + '_range']
			s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
			s.set_value(min(max(light[key], low), high))
			s.set_draw_value(True)
			s.set_size_request(260, -1)
			s.set_format_value_func(lambda _s, v, u=unit: f'{v:.0f}{u}')
			s.connect('value-changed', lambda w, f=setter: self.loading or self._do(
				lambda v=int(w.get_value()): f(self.dev, v)))
			c.append(row(title, s))
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

	def _no_sidetone_card(self, why):
		"""Why there's no sidetone slider: G HUB sets it over HID++ only (0x8300, or 0x0604 on
		Centurion headsets), never through the sound card."""
		self.no_sidetone = card('Sidetone', f'Not over HID++: {why}. That is the only way G HUB sets sidetone (feature '
		                        '0x8300, or 0x0604 on the newer headsets); a sidetone control on the headset’s sound card shows with its sound '
		                        'settings.')
		self.no_sidetone.set_visible(not self.sidetone_elsewhere)
		return self.no_sidetone

	def _sidetone_card(self, info):
		c = card('Sidetone', 'Hear your own voice in the headset.')
		s = slider(0, 100, info['sidetone'])
		s.connect('value-changed', lambda w: self.loading or self._do(
			lambda v=int(w.get_value()): headset.set_sidetone(self.dev, v)))
		c.append(row('Level', s))
		return c

	def _pattern_card(self, info):
		c = card('Polar pattern', 'Which directions the microphone picks up.')
		patterns, current = info['patterns']
		dd = Gtk.DropDown.new_from_strings([features.PATTERNS[p] for p in patterns])
		dd.set_selected(patterns.index(current) if current in patterns else 0)
		dd.connect(NOTIFY_SELECTED, lambda w, _p: self.loading or self._do(
			lambda p=patterns[w.get_selected()]: features.set_polar_pattern(self.dev, p)))
		c.append(row('Pattern', dd))
		return c

	def _angle_card(self, info):
		c = card('Angle snapping', 'Straightens slightly wobbly lines into horizontal or vertical ones.')
		sw = Gtk.Switch(active=info['angle_snapping'], valign=Gtk.Align.CENTER)
		sw.connect(NOTIFY_ACTIVE, lambda w, _p: self.loading or self._do(
			lambda on=w.get_active(): features.set_angle_snapping(self.dev, on)))
		c.append(row('Angle snapping', sw))
		return c

	def _fn_card(self, info):
		inverted, default = info['fn_inversion']
		c = card('Fn keys', 'On: the top row sends F1-F12 only with Fn held'
		         + (' (the keyboard’s default).' if default else '.'))
		sw = Gtk.Switch(active=inverted, valign=Gtk.Align.CENTER)
		sw.connect(NOTIFY_ACTIVE, lambda w, _p: self.loading or self._do(
			lambda on=w.get_active(): features.set_fn_inversion(self.dev, on, self.host)))
		c.append(row('Media keys first', sw))
		return c

	def _analog_card(self, info):
		c = card('Analog keys', 'Switches G HUB offers for keyboards with analog (magnetic) keys.')
		for key, title, setter in (('rapid_trigger', 'Rapid trigger', features.set_rapid_trigger),
		                           ('key_priority', 'Key priority', features.set_key_priority)):
			sw = Gtk.Switch(active=info['analog'][key], valign=Gtk.Align.CENTER)
			sw.connect(NOTIFY_ACTIVE, lambda w, _p, s=setter: self.loading or self._do(
				lambda on=w.get_active(): s(self.dev, on)))
			c.append(row(title, sw))
		profile = info.get('analog_profile') or {}
		for line in analog_summary(profile):
			c.append(label(line, ['muted', 'small'], wrap=True))
		for name, actuation, rapid in analog_keys.per_key_rows(profile, info.get('analog_cids', []),
		                                                       self.device.model.key):
			parts = ([f'actuation {actuation:.2f} mm'] if actuation is not None else []) + \
			        ([f'rapid trigger {rapid:.2f} mm'] if rapid is not None else [])
			c.append(row(name, label(', '.join(parts), ['muted'])))
		return c

	def _game_mode_card(self, info):
		most, chosen, keys = info['game_mode']
		c = card('Game mode', f'Keys to turn off so they can’t interrupt a game (up to {most}).')
		for usage, name in keys:
			sw = Gtk.Switch(active=usage in chosen, valign=Gtk.Align.CENTER)
			sw.connect(NOTIFY_ACTIVE, lambda w, _p, u=usage: self.loading or self._game_key(u, w.get_active()))
			c.append(row(f'Turn off {name}', sw))
		return c

	def _aux_card(self, info):
		c = card('Aux input', 'When the headset’s aux input is on.')
		dd = Gtk.DropDown.new_from_strings(list(headset.AUX_MODES))
		dd.set_selected(min(info['aux'], len(headset.AUX_MODES) - 1))
		dd.connect(NOTIFY_SELECTED, lambda w, _p: self.loading or self._do(
			lambda m=w.get_selected(): headset.set_aux_mode(self.dev, m)))
		c.append(row('Aux', dd))
		return c

	def _usb_ports_card(self, info):
		c = card('USB ports', 'What each of the headset’s USB ports is set up for.')
		for index, setting in info['usb_ports']:
			dd = Gtk.DropDown.new_from_strings(list(headset.PORT_SETTINGS))
			dd.set_selected(min(setting, len(headset.PORT_SETTINGS) - 1))
			dd.connect(NOTIFY_SELECTED, lambda w, _p, i=index: self.loading or self._do(
				lambda s=w.get_selected(): headset.set_usb_port(self.dev, i, s)))
			c.append(row(f'Port {index + 1}', dd))
		return c

	def _mic_select_card(self, info):
		names, active = info['mic_select']
		c = card('Microphone', 'Which of the headset’s microphones it uses.')
		if names:
			dd = Gtk.DropDown.new_from_strings(names)
			dd.set_selected(min(active, len(names) - 1))
			dd.connect(NOTIFY_SELECTED, lambda w, _p: self.loading or self._do(
				lambda i=w.get_selected(): headset.set_mic(self.dev, i)))
			c.append(row('Use', dd))
		return c

	def _switches_card(self, info):
		"""The newer headsets' AI noise reduction, battery saver and footstep detection."""
		state = info['headset_switches']
		c = card('Headset features', 'Settings kept in the headset.')
		for feature, title in headset.SWITCHES.items():
			if feature not in state:
				continue
			sw = Gtk.Switch(active=state[feature], valign=Gtk.Align.CENTER)
			sw.connect(NOTIFY_ACTIVE, lambda w, _p, f=feature: self.loading or self._do(
				lambda on=w.get_active(): headset.set_switch(self.dev, f, on)))
			c.append(row(title, sw))
		if 'ai_level' in state:
			dd = Gtk.DropDown.new_from_strings(list(headset.AI_NR_LEVELS))
			dd.set_selected(min(state['ai_level'], len(headset.AI_NR_LEVELS) - 1))
			dd.connect(NOTIFY_SELECTED, lambda w, _p: self.loading or self._do(
				lambda lv=w.get_selected(): headset.set_ai_nr_level(self.dev, lv)))
			c.append(row('AI noise reduction level', dd))
		return c

	def _onboard_eq_card(self, info):
		"""The newer headsets' onboard equalizer (0x0636): gains per band, sent with G HUB's own filter
		maths (centurion_eq.py); Save keeps them in the headset."""
		bands = info['onboard_eq']
		c = card('Headset equalizer', 'The equalizer inside the headset (G HUB’s filter maths). Changes apply '
		         'right away; Save keeps them on the headset.')
		sliders, pending = [], {}

		def send(save=False):
			pending.pop('id', None)
			gains = [s.get_value() for s in sliders]
			self._do(lambda: centurion_eq.set_gains(self.dev, gains, save))
			return False

		def changed(_w):
			if self.loading:
				return
			if 'id' in pending:
				GLib.source_remove(pending['id'])
			pending['id'] = GLib.timeout_add(300, send)      # ours: one write when a slider stops
		low, high = centurion_eq.GAIN_RANGE
		for freq, gain, _q in bands:
			s = slider(low, high, gain)
			s.connect('value-changed', changed)
			sliders.append(s)
			c.append(row(f'{freq / 1000:g} kHz' if freq >= 1000 else f'{freq} Hz', s))
		save = Gtk.Button(label='Save to headset', halign=Gtk.Align.END)
		save.connect('clicked', lambda _b: send(True))
		c.append(save)
		return c

	def _anc_card(self, info):
		"""The newer headsets' noise cancelling (0x0605): the mode, and what the headset's button does."""
		mode, short, long_mode = info['anc']
		c = card('Noise cancelling', 'What the headset does with outside sound, and what its button switches between.')
		names = list(headset.ANC_MODES)
		dd = Gtk.DropDown.new_from_strings(names)
		dd.set_selected(mode if mode < len(names) else 0)
		dd.connect(NOTIFY_SELECTED, lambda w, _p: self.loading or self._do(
			lambda m=w.get_selected(): headset.set_anc_mode(self.dev, m)))
		c.append(row('Mode', dd))
		chosen = set(short)
		long_dd = Gtk.DropDown.new_from_strings(names)
		long_dd.set_selected(long_mode if long_mode < len(names) else 0)

		def save(*_):
			if not self.loading:
				self._do(lambda s=sorted(chosen), lm=long_dd.get_selected(): headset.set_anc_button(self.dev, s, lm))
		for m, name in enumerate(names):
			sw = Gtk.Switch(active=m in chosen, valign=Gtk.Align.CENTER)

			def toggled(w, _p, m=m):
				(chosen.add if w.get_active() else chosen.discard)(m)
				save()
			sw.connect(NOTIFY_ACTIVE, toggled)
			c.append(row(f'Button: {name}', sw))
		long_dd.connect(NOTIFY_SELECTED, save)
		c.append(row('Button held', long_dd))
		return c

	def _bass_card(self, info):
		c = card('Bass', 'The headset\'s own bass level.')
		s = slider(0, 100, info['bass_tone'])
		s.connect('value-changed', lambda w: self.loading or self._do(
			lambda v=int(w.get_value()): features.set_bass_tone(self.dev, v)))
		c.append(row('Level (%)', s))
		return c

	def _mic_card(self, info):
		mic = info['mic']
		c = card('Microphone', 'The mic\'s own mute, gain, headphone level and how much of the mic you hear (its knob does the same).')
		if 'muted' in mic:
			c.append(self._mic_mute_row(mic))
		if 'gain' in mic:
			c.append(self._mic_gain_row(mic))
		if 'plugged' in mic:
			c.append(row('Headphones', label('Plugged in' if mic['plugged'] else 'Not plugged in', ['muted'])))
		if 'headphones' in mic:
			h = slider(0, 100, mic['headphones'])
			h.connect('value-changed', lambda w: self.loading or self._do(
				lambda v=int(w.get_value()): features.set_headphone_level(self.dev, v)))
			c.append(row('Headphones (%)', h))
		if 'monitoring' in mic:
			m = slider(0, 100, mic['monitoring'])
			m.connect('value-changed', lambda w: self.loading or self._do(
				lambda v=int(w.get_value()): features.set_mic_monitoring(self.dev, v)))
			c.append(row('Mic monitoring (%)', m))
		return c

	def _mic_mute_row(self, mic):
		sw = Gtk.Switch(active=mic['muted'], valign=Gtk.Align.CENTER)
		if mic.get('centurion'):
			set_muted = headset.set_centurion_mic_muted
		else:
			def set_muted(dev, on):
				features.set_mic_muted(dev, on, self.device.usb_id)
		sw.connect(NOTIFY_ACTIVE, lambda w, _p: self.loading or self._do(
			lambda on=w.get_active(): set_muted(self.dev, on)))
		return row('Mute', sw)

	def _mic_gain_row(self, mic):
		if 'gain_range' in mic:                           # the headset's own units (0x0611)
			s = slider(*mic['gain_range'], mic['gain'])
			s.connect('value-changed', lambda w: self.loading or self._do(
				lambda v=int(w.get_value()): headset.set_centurion_mic_gain(self.dev, v)))
			return row('Gain', s)
		s = slider(0, 100, mic['gain'])
		s.connect('value-changed', lambda w: self.loading or self._do(
			lambda v=int(w.get_value()): features.set_mic_gain(self.dev, v, mic['gain_type'])))
		return row('Gain (%)', s)

	def _charging_card(self, info):
		c = card('Charging', 'Let the device charge from this computer.')
		sw = Gtk.Switch(active=info['charging'], valign=Gtk.Align.CENTER)
		sw.connect(NOTIFY_ACTIVE, lambda w, _p: self.loading or self._do(
			lambda on=w.get_active(): features.set_charging(self.dev, on)))
		c.append(row('Charge', sw))
		return c

	def _device_eq_card(self, info):
		eq = info['device_eq']
		c = card('Headset equalizer', 'The equalizer inside the headset: it works on any computer or console.')
		sw = Gtk.Switch(active=eq['on'], valign=Gtk.Align.CENTER)
		sw.connect(NOTIFY_ACTIVE, lambda w, _p: self.loading or self._do(
			lambda on=w.get_active(): features.set_device_eq_on(self.dev, on)))
		c.append(row('On', sw))
		gains = list(eq['gains'])
		for i, hz in enumerate(eq['freqs'][:len(gains)]):
			s = slider(eq['low'], eq['high'], gains[i])
			s.connect('value-changed', lambda w, n=i: self._eq_band(gains, n, w.get_value()))
			c.append(row(f'{hz / 1000:g} kHz' if hz >= 1000 else f'{hz} Hz', s))
		return c

	def _eq_band(self, gains, n, value):
		if self.loading or round(value) == gains[n]:
			return
		gains[n] = round(value)
		self._do(lambda g=list(gains): features.set_device_eq(self.dev, g))

	def _hosts_card(self, info):
		count, current = info['hosts']
		c = card('Easy-Switch', 'Which computer the device works with. Switching sends it to the other '
		         'computer right away.')
		buttons = box(Gtk.Orientation.HORIZONTAL, 10)
		names = info.get('host_names') or []
		for h in range(count):
			name = (names[h] if h < len(names) else None) or f'Computer {h + 1}'
			b = Gtk.Button(label=name + (' (this one)' if h == current else ''))
			b.set_sensitive(h != current)
			b.connect('clicked', lambda _w, n=h: self._do(lambda: features.set_host(self.dev, n)))
			buttons.append(b)
		c.append(buttons)
		return c

	def _game_key(self, usage, off):
		keys = [k for k in features.game_mode_keys(self.device.model.key) if k != usage] + ([usage] if off else [])
		features.save_game_mode_keys(self.device.model.key, keys)
		self._do(lambda: features.apply_game_mode(self.dev, keys))

	def _mode_card(self, info):
		c = card('On-board memory', 'On: the device runs the settings stored in it. Off: it follows software; '
		         'lighting changes here may need this off on some keyboards.')
		sw = Gtk.Switch(active=info['mode'] == mouse.MODE_ONBOARD)
		sw.connect(NOTIFY_ACTIVE, lambda w, _p: self.loading or self._do(
			lambda on=w.get_active(): self.dev.call(features.ONBOARD, 1,
			                                        bytes([mouse.MODE_ONBOARD if on else mouse.MODE_HOST]))))
		c.append(row('Use on-board memory', sw))
		count, active = info.get('profiles', (0, 0))
		if count > 1:
			dd = Gtk.DropDown.new_from_strings([f'Profile {n}' for n in range(1, count + 1)])
			dd.set_selected(active - 1 if 1 <= active <= count else 0)
			dd.connect(NOTIFY_SELECTED, lambda w, _p: self.loading or self._do(
				lambda n=w.get_selected() + 1: self.dev.call(features.ONBOARD, 3, bytes([0, n]))))
			c.append(row('Active profile (stored in the device)', dd))
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
		return zone_card(zone, lambda: self.loading, lambda job: self._do(job), lambda: self.dev)
