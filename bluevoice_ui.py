"""The page of a Blue VO!CE headset (G Pro X, G Pro X Wireless, G733).

These pages only edit config.json and show status.json; the engine (engine.py, a systemd user
service) does the processing, so the virtual microphone keeps working with the app closed.
"""
import copy
import json
import os
import threading

from gi.repository import Adw, GLib, Gtk

import devices
import headset_ui
import presets
import pw
import service
import store
from ui import (APP_DIR, NOTIFY_ACTIVE, box, button_widget, device_icon, device_sidebar, format_value, label, meter_bar,
                nav_button, page_header, scrolled, set_meter)

APP_TITLE = 'Blue VO!CE'
MY_PRESETS = 'My presets'
SAVE_DELAY_MS = 150
CUSTOM = 'Custom'
PAGES = ('voice', 'effects', 'microphone', 'presets', 'equalizer', 'headset')
HEADSET_PAGES = (('equalizer', 'Equalizer', 'multimedia-equalizer-symbolic'),
                 ('headset', 'Headset', 'audio-headset-symbolic'))


# --- Voice page ----------------------------------------------------------------------------

class VoicePage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24, css_classes=['page'])
		self.win = win
		self.append(page_header('Voice', 'Logitech Blue VO!CE, applied to your microphone in real time.',
		                        button_widget('Save as preset', ['ghost'], self._save_as)))

		hero = box(Gtk.Orientation.HORIZONTAL, 20, ['card', 'hero'])
		left = box(spacing=6, hexpand=True)
		left.append(label(APP_TITLE, ['muted', 'small']))
		self.state_word = label('On', ['big-word'])
		left.append(self.state_word)
		self.route = label('', ['muted', 'small'], wrap=True)
		left.append(self.route)
		hero.append(left)
		self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
		self.switch.connect(NOTIFY_ACTIVE, self._on_switch)
		hero.append(self.switch)
		self.append(hero)

		meters = box(spacing=12, css=['card'])
		meters.append(label('Levels', ['section-title']))
		self.bars = {}
		for key, text in (('in', 'Microphone'), ('out', APP_TITLE)):
			row = box(Gtk.Orientation.HORIZONTAL, 14)
			row.append(label(text, ['muted'], width_chars=11))
			bar = meter_bar()
			row.append(bar)
			value = label('—', ['value'], width_chars=7, xalign=1.0)
			row.append(value)
			meters.append(row)
			self.bars[key] = (bar, value)
		self.append(meters)

		self.append(label('Presets', ['section-title']))
		self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10,
		                        min_children_per_line=2, max_children_per_line=6, homogeneous=True)
		self.append(self.flow)
		self.mine_title = label(MY_PRESETS, ['section-title'])
		self.append(self.mine_title)
		self.mine_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10,
		                             min_children_per_line=2, max_children_per_line=6, homogeneous=True)
		self.append(self.mine_flow)
		self.preset_buttons = {}
		self.load()

	def load(self):
		self.win.loading = True
		self.switch.set_active(self.win.cfg.get('enabled', True))
		self.win.loading = False
		self._state_text()
		for flow in (self.flow, self.mine_flow):
			while (child := flow.get_first_child()):
				flow.remove(child)
		self.preset_buttons = {}
		origin = f'G HUB · {store.MODEL_NAMES[self.win.model]}'
		for _key, name, params in self.win.ghub_presets:
			self._add_preset(self.flow, name, params, origin)
		mine = store.list_user_presets()
		for name in mine:
			params = store.load_user_preset(name)
			if params:
				self._add_preset(self.mine_flow, name, params, 'Saved')
		self.mine_title.set_visible(bool(mine))
		self.mark_selected()

	def _add_preset(self, flow, name, params, origin):
		b = Gtk.Button()
		b.add_css_class('preset')
		inner = box(spacing=2)
		inner.append(label(name, ['preset-name']))
		inner.append(label(origin, ['muted', 'small']))
		b.set_child(inner)
		b.connect('clicked', lambda _w: self.win.apply_preset(name, params))
		flow.append(b)
		self.preset_buttons[name] = b

	def mark_selected(self):
		current = self.win.cfg.get('preset')
		for name, b in self.preset_buttons.items():
			(b.add_css_class if name == current else b.remove_css_class)('selected')

	def _state_text(self):
		on = self.win.cfg.get('enabled', True)
		self.state_word.set_text('On' if on else 'Off')
		preset = self.win.cfg.get('preset', CUSTOM)
		self.route.set_text(f'Preset: {preset}' if on else 'Your voice passes through unprocessed.')

	def _on_switch(self, *_):
		if self.win.loading:
			return
		self.win.cfg['enabled'] = self.switch.get_active()
		self._state_text()
		self.win.save_soon()

	def _save_as(self):
		dialog = Adw.AlertDialog(heading='Save preset', body='Saves the current Effects settings.')
		entry = Gtk.Entry(placeholder_text='Preset name', activates_default=True)
		current = self.win.cfg.get('preset', '')
		if current and current != CUSTOM:
			entry.set_text(current if current in store.list_user_presets() else f'{current} (mine)')
		dialog.set_extra_child(entry)
		dialog.add_response('cancel', 'Cancel')
		dialog.add_response('save', 'Save')
		dialog.set_response_appearance('save', Adw.ResponseAppearance.SUGGESTED)
		dialog.set_default_response('save')

		def done(_d, response):
			name = store.safe_name(entry.get_text())
			if response == 'save' and entry.get_text().strip():
				store.save_user_preset(name, self.win.cfg['params'])
				self.win.cfg['preset'] = name
				self.win.save_soon()
				self.win.reload_presets()
				self.win.toast(f'Saved “{name}”')
		dialog.connect('response', done)
		dialog.present(self.win)

	def update_status(self, status):
		ready = status.get('state') == 'running'
		set_meter(*self.bars['in'], status.get('meter_in', -120) if ready else -120)
		set_meter(*self.bars['out'], status.get('meter_out', -120) if ready else -120)


# --- Effects page --------------------------------------------------------------------------

class EffectsPage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.append(page_header('Effects', 'Every Blue VO!CE stage, in processing order. Changes apply live.',
		                        button_widget('Reset to preset', ['ghost'], win.reset_to_preset)))
		self.controls = {}   # param -> (scale, value label, unit)
		self.switches = {}   # enable param -> (switch, card)

		out_card = box(spacing=10, css=['card'])
		self._slider_row(out_card, *presets.OUTPUT_PARAM)
		self.append(out_card)

		for _key, title, hint, enable, sliders in presets.STAGES:
			card = box(spacing=10, css=['card'])
			head = box(Gtk.Orientation.HORIZONTAL, 16)
			titles = box(spacing=2, hexpand=True)
			titles.append(label(title, ['stage-title']))
			titles.append(label(hint, ['muted', 'small'], wrap=True))
			head.append(titles)
			if enable:
				sw = Gtk.Switch(valign=Gtk.Align.CENTER)
				sw.connect(NOTIFY_ACTIVE, lambda w, _pspec, p=enable: self._on_switch(p, w))
				head.append(sw)
				self.switches[enable] = (sw, card)
			card.append(head)
			for spec in sliders:
				self._slider_row(card, *spec)
			self.append(card)
		self.load()

	def _slider_row(self, parent, param, text, lo, hi, step, unit):
		row = box(Gtk.Orientation.HORIZONTAL, 14)
		row.append(label(text, ['muted'], width_chars=18))
		scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
		scale.set_hexpand(True)
		scale.set_draw_value(False)
		value = label('', ['value'], width_chars=10, xalign=1.0)
		scale.connect('value-changed', lambda w, p=param, u=unit, v=value: self._on_scale(p, u, w, v))
		row.append(scale)
		row.append(value)
		parent.append(row)
		self.controls[param] = (scale, value, unit)

	def load(self):
		params = self.win.cfg['params']
		self.win.loading = True
		for param, (scale, value, unit) in self.controls.items():
			v = presets.to_ui(param, params.get(param, presets.DEFAULTS[param]))
			scale.set_value(v)
			value.set_text(format_value(scale.get_value(), unit))
		for param, (sw, card) in self.switches.items():
			on = bool(params.get(param, 0))
			sw.set_active(on)
			(card.remove_css_class if on else card.add_css_class)('off')
		self.win.loading = False

	def _on_scale(self, param, unit, scale, value):
		v = scale.get_value()
		value.set_text(format_value(v, unit))
		if self.win.loading:
			return
		self.win.set_param(param, presets.from_ui(param, v))

	def _on_switch(self, param, sw):
		card = self.switches[param][1]
		(card.remove_css_class if sw.get_active() else card.add_css_class)('off')
		if self.win.loading:
			return
		self.win.set_param(param, 1 if sw.get_active() else 0)


# --- Microphone page -----------------------------------------------------------------------

class MicrophonePage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.append(page_header('Microphone', 'Where the sound comes from, and where it goes.'))

		card = box(spacing=12, css=['card'])
		card.append(label('Input', ['section-title']))
		card.append(label('The microphone Blue VO!CE processes. Automatic picks the headset’s when it is '
		                  'connected, otherwise your default microphone.', ['muted', 'small'], wrap=True))
		self.inputs = [('auto', 'Automatic')]
		self.dropdown = Gtk.DropDown.new_from_strings([d for _, d in self.inputs])
		self.dropdown.connect('notify::selected', self._on_input)
		card.append(self.dropdown)
		card.append(label('Headset', ['section-title']))
		card.append(label('G HUB tunes its Blue VO!CE presets per headset. Automatic chooses from the '
		                  'microphone in use.', ['muted', 'small'], wrap=True))
		self.models = [('auto', 'Automatic')] + list(store.MODEL_NAMES.items())
		self.model_dropdown = Gtk.DropDown.new_from_strings([d for _, d in self.models])
		self.model_dropdown.connect('notify::selected', self._on_model)
		card.append(self.model_dropdown)
		self.append(card)

		card = box(spacing=14, css=['card'])
		card.append(label('Output', ['section-title']))
		card.append(label('Apps such as Discord, OBS and your browser see a new input device called '
		                  '“Blue VO!CE Microphone”. Pick it there, or make it the default below.',
		                  ['muted', 'small'], wrap=True))
		self.default_switch = self._switch_row(card, 'Use as default microphone',
			'Apps that use the system default get Blue VO!CE automatically.', self._on_default)
		card.append(label('Blue VO!CE adds 8 ms of delay: 5.3 ms of buffering plus 2.7 ms of look-ahead '
		                  'in Logitech’s processing.', ['muted', 'small'], wrap=True))
		self.append(card)

		card = box(spacing=14, css=['card'])
		card.append(label('Background service', ['section-title']))
		self.service_state = label('', ['muted'], wrap=True)
		card.append(self.service_state)
		self.autostart = self._switch_row(card, 'Start at login',
			'Keeps the virtual microphone available without opening this app.', self._on_autostart)
		row = box(Gtk.Orientation.HORIZONTAL, 10)
		row.append(button_widget('Restart', ['ghost'], self._restart))
		self.stop_button = button_widget('Stop', ['danger'], self._stop)
		row.append(self.stop_button)
		card.append(row)
		self.append(card)
		self.load()

	def _switch_row(self, parent, title, hint, on_change):
		row = box(Gtk.Orientation.HORIZONTAL, 16)
		titles = box(spacing=2, hexpand=True)
		titles.append(label(title))
		titles.append(label(hint, ['muted', 'small'], wrap=True))
		row.append(titles)
		sw = Gtk.Switch(valign=Gtk.Align.CENTER)
		sw.connect(NOTIFY_ACTIVE, lambda *_: on_change(sw))
		row.append(sw)
		parent.append(row)
		return sw

	def load(self):
		self.win.loading = True
		self.default_switch.set_active(self.win.cfg.get('make_default', False))
		chosen = self.win.cfg.get('headset', 'auto')
		self.model_dropdown.set_selected(next((i for i, (k, _) in enumerate(self.models) if k == chosen), 0))
		self.autostart.set_active(service.is_enabled())
		self.win.loading = False
		self.refresh_inputs()

	def refresh_inputs(self):
		def work():
			srcs = pw.sources()
			GLib.idle_add(self._fill_inputs, srcs)
		threading.Thread(target=work, daemon=True).start()

	def _fill_inputs(self, srcs):
		wanted = self.win.cfg.get('input', 'auto')
		inputs = [('auto', 'Automatic')] + [(s['name'], s['description']) for s in srcs]
		if wanted != 'auto' and wanted not in [n for n, _ in inputs]:
			inputs.append((wanted, f'{wanted} (not connected)'))
		if inputs == self.inputs and self.dropdown.get_selected() != Gtk.INVALID_LIST_POSITION:
			return
		self.inputs = inputs
		self.win.loading = True
		self.dropdown.set_model(Gtk.StringList.new([d for _, d in inputs]))
		self.dropdown.set_selected(next(i for i, (n, _) in enumerate(inputs) if n == wanted))
		self.win.loading = False

	def _on_input(self, *_):
		i = self.dropdown.get_selected()
		if self.win.loading or i == Gtk.INVALID_LIST_POSITION or i >= len(self.inputs):
			return
		self.win.cfg['input'] = self.inputs[i][0]
		self.win.save_soon()

	def _on_model(self, *_):
		i = self.model_dropdown.get_selected()
		if self.win.loading or i == Gtk.INVALID_LIST_POSITION:
			return
		self.win.cfg['headset'] = self.models[i][0]
		self.win.save_soon()
		self.win.refresh_model()

	def _on_default(self, sw):
		if not self.win.loading:
			self.win.cfg['make_default'] = sw.get_active()
			self.win.save_soon()

	def _on_autostart(self, sw):
		if not self.win.loading:
			threading.Thread(target=service.set_autostart, args=(sw.get_active(),), daemon=True).start()

	def _restart(self):
		threading.Thread(target=service.restart, daemon=True).start()
		self.win.toast('Restarting Blue VO!CE…')

	def _stop(self):
		threading.Thread(target=service.stop, daemon=True).start()
		self.win.toast('Stopped. The virtual microphone is gone until you restart it.')

	def update_status(self, status, active):
		state = status.get('state')
		if not active:
			text = 'Not running. Press Restart to start it.'
		elif state == 'running':
			text = 'Running.'
		elif state == 'starting':
			text = 'Starting…'
		else:
			text = status.get('error') or 'Problem: see journalctl --user -u lghub-bluevoice'
		self.service_state.set_text(text)
		self.stop_button.set_sensitive(active)


# --- Presets page --------------------------------------------------------------------------

class PresetsPage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.append(page_header(MY_PRESETS, 'Presets you saved. Logitech’s are on the Voice page.',
		                        button_widget('Import…', ['ghost'], self._import)))
		self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
		self.list.add_css_class('plain')
		self.append(self.list)
		self.empty = label('Nothing saved yet. Tune the Effects page, then use “Save as preset” on the '
		                   'Voice page.', ['muted'], wrap=True)
		self.append(self.empty)
		self.load()

	def load(self):
		while (row := self.list.get_first_child()):
			self.list.remove(row)
		names = store.list_user_presets()
		self.empty.set_visible(not names)
		for name in names:
			row = box(Gtk.Orientation.HORIZONTAL, 10)
			row.append(label(name, ['preset-name'], hexpand=True))
			row.append(button_widget('Apply', ['apply'], lambda n=name: self._apply(n)))
			row.append(button_widget('Export…', ['ghost'], lambda n=name: self._export(n)))
			row.append(button_widget('Delete', ['danger'], lambda n=name: self._delete(n)))
			self.list.append(row)

	def _apply(self, name):
		params = store.load_user_preset(name)
		if params:
			self.win.apply_preset(name, params)

	def _delete(self, name):
		store.delete_user_preset(name)
		self.win.reload_presets()
		self.win.toast(f'Deleted “{name}”')

	def _export(self, name):
		dialog = Gtk.FileDialog(initial_name=f'{store.safe_name(name)}.json')

		def done(d, result):
			try:
				path = d.save_finish(result).get_path()
			except GLib.Error:
				return
			with open(path, 'w') as f:
				json.dump({'name': name, 'params': store.load_user_preset(name)}, f, indent=2)
			self.win.toast(f'Exported to {os.path.basename(path)}')
		dialog.save(self.win.get_root(), None, done)

	def _import(self):
		dialog = Gtk.FileDialog()

		def done(d, result):
			try:
				path = d.open_finish(result).get_path()
				with open(path) as f:
					data = json.load(f)
				params = {k: v for k, v in data['params'].items() if k in presets.DEFAULTS}
				name = store.safe_name(data.get('name') or os.path.splitext(os.path.basename(path))[0])
			except (GLib.Error, OSError, ValueError, KeyError, TypeError):
				self.win.toast('That file isn’t a Blue VO!CE preset.')
				return
			store.save_user_preset(name, params)
			self.win.reload_presets()
			self.win.toast(f'Imported “{name}”')
		dialog.open(self.win.get_root(), None, done)


# --- the headset view --------------------------------------------------------------------

class BlueVoiceView(Gtk.Box):
	"""A Blue VO!CE headset's page: Blue VO!CE, the equalizer and the headset's own settings.
	Blue VO!CE itself keeps running in the background with any microphone."""

	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
		self.window = win
		self.loading = False
		self._save_id = 0
		self.device_title = APP_TITLE
		self.cfg = store.load_config()
		self.hint = None           # preset set of the headset whose page is open
		self.model = store.headset_model(self.cfg, store.read_status())
		self.ghub_presets = store.ghub_presets(self.model)
		self.base_params = copy.deepcopy(self.cfg['params'])  # what "Reset to preset" returns to

		self.banner = Adw.Banner(title='Logitech’s Blue VO!CE files are missing. Run ./install.sh again.')
		self.banner.set_revealed(not os.path.exists(store.APO_DLL))
		self.append(self.banner)
		self.root = box(Gtk.Orientation.HORIZONTAL, vexpand=True)
		self.append(self.root)

		self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True)
		self.voice_page = VoicePage(self)
		self.effects_page = EffectsPage(self)
		self.mic_page = MicrophonePage(self)
		self.presets_page = PresetsPage(self)
		self.eq_page = headset_ui.EqualizerPage(self)
		self.headset_page = headset_ui.HeadsetPage(self)
		for page, name in ((self.voice_page, 'voice'), (self.effects_page, 'effects'),
		                   (self.mic_page, 'microphone'), (self.presets_page, 'presets'),
		                   (self.eq_page, 'equalizer'), (self.headset_page, 'headset')):
			self.stack.add_named(scrolled(page), name)
		self.sidebar = None
		self.set_device(None)
		self.root.append(self.stack)
		self.show_page('voice')

		self._service_active = service.is_active()
		if not self._service_active and service.installed():
			threading.Thread(target=service.start, daemon=True).start()
		GLib.timeout_add(100, self._poll_status)
		GLib.timeout_add_seconds(3, self._poll_slow)

	def set_device(self, device):
		"""Title the sidebar after the headset it was opened from (or Blue VO!CE itself)."""
		title = device.name if device else APP_TITLE
		self.headset_page.set_device(device)
		self.hint = devices.blue_voice_model(device)
		self.refresh_model()
		if self.sidebar and title == self.device_title:
			return
		self.device_title = title
		if self.sidebar:
			self.root.remove(self.sidebar)
		self.sidebar = self._build_sidebar(device)
		self.root.prepend(self.sidebar)
		page = self.stack.get_visible_child_name() or 'voice'
		self.show_page(page if page in self.nav_buttons else 'voice')

	def toast(self, text):
		self.window.toast(text)

	def _build_sidebar(self, device):
		icon_path = os.path.join(APP_DIR, 'lghub-bluevoice.svg')
		if device:
			logo = device_icon(device, 32)
		elif os.path.exists(icon_path):
			logo = Gtk.Image.new_from_file(icon_path)
		else:
			logo = Gtk.Image.new_from_icon_name('audio-input-microphone-symbolic')
		side = device_sidebar(self.window.show_home, logo, self.device_title,
		                      APP_TITLE if device else 'Virtual microphone')

		nav = box(spacing=4)
		self.nav_buttons = {}
		for key, text, icon_name in (
			('voice', 'Voice', 'audio-input-microphone-symbolic'),
			('effects', 'Effects', 'preferences-other-symbolic'),
			('microphone', 'Microphone', 'audio-card-symbolic'),
			('presets', MY_PRESETS, 'view-list-symbolic'),
		):
			b = nav_button(text, icon_name, lambda k=key: self.show_page(k))
			nav.append(b)
			self.nav_buttons[key] = b
		if device:
			nav.append(label('Headset', ['muted', 'small'], margin_top=14, margin_bottom=4, margin_start=12))
			for key, text, icon_name in HEADSET_PAGES:
				b = nav_button(text, icon_name, lambda k=key: self.show_page(k))
				nav.append(b)
				self.nav_buttons[key] = b
		side.append(nav)
		side.append(box(vexpand=True))

		card = box(spacing=8, css=['card'])
		card.append(label('Virtual microphone', ['muted', 'small']))
		headline = box(Gtk.Orientation.HORIZONTAL, 8)
		self.side_state = label('—', ['big-word'], hexpand=True)
		headline.append(self.side_state)
		self.conn_label = label('●', ['muted', 'small'], valign=Gtk.Align.CENTER)
		headline.append(self.conn_label)
		card.append(headline)
		self.side_input = label('', ['muted', 'small'], wrap=True, max_width_chars=24)
		card.append(self.side_input)
		card.append(label('Voice level', ['muted', 'small']))
		self.side_bar = meter_bar()
		card.append(self.side_bar)
		side.append(card)
		return side

	def show_page(self, key):
		self.stack.set_visible_child_name(key)
		for k, b in self.nav_buttons.items():
			(b.add_css_class if k == key else b.remove_css_class)('active')
		if key == 'microphone':
			self.mic_page.refresh_inputs()
		elif key == 'equalizer':
			self.eq_page.refresh_targets()
		elif key == 'headset':
			self.headset_page.refresh()

	# --- settings ------------------------------------------------------------------------

	def save_soon(self):
		if self._save_id:
			GLib.source_remove(self._save_id)
		self._save_id = GLib.timeout_add(SAVE_DELAY_MS, self._save_now)

	def _save_now(self):
		self._save_id = 0
		store.save_config(self.cfg)
		return False

	def set_param(self, param, value):
		self.cfg['params'][param] = value
		if self.cfg.get('preset') != CUSTOM and self.cfg['params'] != self.base_params:
			self.cfg['preset'] = CUSTOM
			self.voice_page.mark_selected()
			self.voice_page._state_text()
		self.save_soon()

	def apply_preset(self, name, params):
		self.cfg['params'] = {**presets.DEFAULTS, **copy.deepcopy(params)}
		self.cfg['preset'] = name
		self.base_params = copy.deepcopy(self.cfg['params'])
		self.effects_page.load()
		self.voice_page.mark_selected()
		self.voice_page._state_text()
		self.save_soon()
		self.toast(f'Preset: {name}')

	def reset_to_preset(self):
		self.cfg['params'] = copy.deepcopy(self.base_params)
		self.effects_page.load()
		self.save_soon()

	def reload_presets(self):
		self.voice_page.load()
		self.presets_page.load()

	def refresh_model(self, status=None):
		"""Switch the G HUB preset list when the headset model (chosen or detected) changes."""
		model = store.headset_model(self.cfg, status if status is not None else store.read_status(), self.hint)
		if model != self.model or not self.ghub_presets:
			self.model = model
			self.ghub_presets = store.ghub_presets(model)
			self.voice_page.load()

	# --- status --------------------------------------------------------------------------

	def _poll_status(self):
		if self.get_mapped():   # nothing to show while another device's page is open
			self._show_status()
		return True

	def _show_status(self):
		status = store.read_status()
		if status.get('updated', 0) <= GLib.get_real_time() / 1e6 - 3:
			status = {'state': 'stopped'}  # the engine isn't running (or is stuck)
		if self.cfg.get('headset', 'auto') == 'auto' and status.get('input'):
			self.refresh_model(status)
		self.voice_page.update_status(status)
		self.mic_page.update_status(status, self._service_active)
		self._show_sidebar_status(status)

	def _show_sidebar_status(self, status):
		state = status.get('state')
		running = state == 'running'
		standby = running and not status.get('listening', True)
		word, dot, css = {
			'running': ('Active', '● Running', 'ok'),
			'starting': ('Starting', '● Starting', 'warn'),
			'error': ('Problem', '● Error', 'err'),
		}.get(state, ('Off', '● Stopped', 'muted'))
		if standby:
			word = 'Standby'
		elif running and not status.get('enabled', True):
			word = 'Bypassed'
		self.side_state.set_text(word)
		for c in ('ok', 'warn', 'err', 'muted'):
			self.conn_label.remove_css_class(c)
		self.conn_label.set_text(dot)
		self.conn_label.add_css_class(css)
		self.side_input.set_text(self._sidebar_detail(status, state, standby))
		self.side_bar.set_value(max(0.0, status.get('meter_out', -120) + 60) if running else 0)

	@staticmethod
	def _sidebar_detail(status, state, standby):
		if standby:
			return f'Ready. Your microphone opens when an app uses {APP_TITLE}.'
		if state == 'running':
			inp = status.get('input')
			return f"From {inp['description']}" if inp else 'Waiting for a microphone'
		if state == 'error':
			return status.get('error', '')
		return ''

	def _poll_slow(self):
		def work():
			active = service.is_active()
			GLib.idle_add(setattr, self, '_service_active', active)
		threading.Thread(target=work, daemon=True).start()
		return True
