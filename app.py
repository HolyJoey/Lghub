#!/usr/bin/env python3
"""Blue VO!CE for Linux (GTK4 + libadwaita).

The app only edits config.json and shows status.json; the engine (engine.py, a systemd user
service) does the processing, so the virtual microphone keeps working with the app closed.
"""
import copy
import json
import os
import sys
import threading

import gi

import presets
import pw
import service
import store

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID = 'dev.local.LghubBlueVoice'
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ACCENT = '#2f8cff'
SAVE_DELAY_MS = 150
CUSTOM = 'Custom'

CSS = f"""
window {{ font-family: Manrope, Cantarell, sans-serif; }}
.app-bg {{ background: #111317; color: #eceef2; }}
.sidebar {{ background: #0c0e11; border-right: 1px solid #22262e; padding: 24px 16px; }}
.brand-title {{ font-weight: 700; font-size: 15px; }}
.muted {{ color: #9aa0ad; }}
.small {{ font-size: 12px; }}
button.nav {{ min-height: 44px; padding: 0 12px; border-radius: 10px; background: transparent;
  color: #9aa0ad; font-weight: 500; box-shadow: none; border: none; }}
button.nav:hover {{ background: #161a20; }}
button.nav.active {{ background: #1c2027; color: #eceef2; font-weight: 600; }}
button.nav.active image {{ color: {ACCENT}; }}
.card {{ background: #161a20; border: 1px solid #22262e; border-radius: 14px; padding: 16px 20px; }}
.card.off {{ opacity: 0.55; }}
.hero {{ background: linear-gradient(135deg, #14243a, #161a20 60%); border-color: #1f3a5c; }}
.big-word {{ font-size: 26px; font-weight: 700; }}
.mono {{ font-family: "JetBrains Mono", "JetBrainsMono Nerd Font", monospace; }}
.ok {{ color: #6fdc9a; }}
.warn {{ color: #ffc14d; }}
.err {{ color: #ff8a8a; }}
.page {{ padding: 32px 40px; }}
.page-title {{ font-size: 26px; font-weight: 700; }}
.section-title {{ font-size: 15px; font-weight: 600; }}
.stage-title {{ font-size: 16px; font-weight: 700; }}
button.apply {{ background: {ACCENT}; color: #04121f; font-weight: 700; border-radius: 10px;
  min-height: 40px; padding: 0 20px; border: none; box-shadow: none; }}
button.ghost {{ background: transparent; border: 1px solid #2c313b; color: #eceef2; font-weight: 600;
  border-radius: 10px; min-height: 40px; padding: 0 16px; box-shadow: none; }}
button.danger {{ background: transparent; border: 1px solid #5a2a2a; color: #ff8a8a; font-weight: 600;
  border-radius: 10px; min-height: 40px; padding: 0 16px; box-shadow: none; }}
button.preset {{ background: #161a20; border: 1px solid #22262e; border-radius: 12px; min-height: 64px;
  min-width: 168px; padding: 8px 14px; box-shadow: none; color: #eceef2; }}
button.preset:hover {{ background: #1b1f26; }}
button.preset.selected {{ border: 2px solid {ACCENT}; background: #15223a; padding: 7px 13px; }}
.preset-name {{ font-weight: 700; }}
levelbar.meter trough {{ min-height: 8px; background: #262a33; border-radius: 4px; border: none; }}
levelbar.meter block.filled {{ background: {ACCENT}; border-radius: 4px; }}
levelbar.meter block.high {{ background: #ffc14d; border-radius: 4px; }}
levelbar.meter block.full {{ background: #ff8a8a; border-radius: 4px; }}
levelbar.meter block.empty {{ background: transparent; }}
scale highlight {{ background: {ACCENT}; }}
scale slider {{ background: #eceef2; }}
switch:checked {{ background: {ACCENT}; }}
list.plain {{ background: none; }}
list.plain > row {{ background: #161a20; border: 1px solid #22262e; border-radius: 12px; margin-bottom: 8px; padding: 8px 12px; }}
.value {{ font-family: "JetBrains Mono", "JetBrainsMono Nerd Font", monospace; color: #c9ced8; }}
banner {{ background: #3a2a14; }}
"""


# --- helpers -------------------------------------------------------------------------------

def box(orientation=Gtk.Orientation.VERTICAL, spacing=0, css=None, **kw):
	b = Gtk.Box(orientation=orientation, spacing=spacing, **kw)
	for c in (css or []):
		b.add_css_class(c)
	return b


def label(text, css=None, xalign=0.0, **kw):
	lbl = Gtk.Label(label=text, xalign=xalign, **kw)
	for c in (css or []):
		lbl.add_css_class(c)
	return lbl


def button_widget(text, css=None, on_click=None):
	b = Gtk.Button(label=text)
	for c in (css or []):
		b.add_css_class(c)
	if on_click:
		b.connect('clicked', lambda _w: on_click())
	return b


def page_header(title, subtitle, *buttons):
	header = box(Gtk.Orientation.HORIZONTAL, 12)
	titles = box(spacing=4, hexpand=True)
	titles.append(label(title, ['page-title']))
	titles.append(label(subtitle, ['muted'], wrap=True))
	header.append(titles)
	for b in buttons:
		b.set_valign(Gtk.Align.CENTER)
		header.append(b)
	return header


def format_value(value, unit):
	if unit == 'Hz':
		return f'{value / 1000:.2f} kHz' if value >= 1000 else f'{value:.0f} Hz'
	if unit == 'dB':
		return f'{value:+.1f} dB' if abs(value) >= 0.05 else '0.0 dB'
	if unit == 'ms':
		return f'{value:.1f} ms' if value < 10 else f'{value:.0f} ms'
	if unit == ':1':
		return f'{value:.1f}:1'
	return f'{value:.1f}'


def meter_bar():
	bar = Gtk.LevelBar(min_value=0, max_value=60, hexpand=True, valign=Gtk.Align.CENTER)
	bar.add_css_class('meter')
	for name in list(('low', 'high', 'full')):
		bar.remove_offset_value(name)
	bar.add_offset_value('filled', 48)
	bar.add_offset_value('high', 57)
	bar.add_offset_value('full', 60)
	return bar


def set_meter(bar, value_label, db):
	db = max(-60.0, min(0.0, db))
	bar.set_value(db + 60)
	value_label.set_text('—' if db <= -59.9 else f'{db:.0f} dB')


# --- Voice page ----------------------------------------------------------------------------

class VoicePage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24, css_classes=['page'])
		self.win = win
		self.append(page_header('Voice', 'Logitech Blue VO!CE, applied to your microphone in real time.',
		                        button_widget('Save as preset', ['ghost'], self._save_as)))

		hero = box(Gtk.Orientation.HORIZONTAL, 20, ['card', 'hero'])
		left = box(spacing=6, hexpand=True)
		left.append(label('Blue VO!CE', ['muted', 'small']))
		self.state_word = label('On', ['big-word'])
		left.append(self.state_word)
		self.route = label('', ['muted', 'small'], wrap=True)
		left.append(self.route)
		hero.append(left)
		self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
		self.switch.connect('notify::active', self._on_switch)
		hero.append(self.switch)
		self.append(hero)

		meters = box(spacing=12, css=['card'])
		meters.append(label('Levels', ['section-title']))
		self.bars = {}
		for key, text in (('in', 'Microphone'), ('out', 'Blue VO!CE')):
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
		self.mine_title = label('My presets', ['section-title'])
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
				sw.connect('notify::active', lambda w, _pspec, p=enable: self._on_switch(p, w))
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
		card.append(label('The microphone Blue VO!CE processes. Automatic picks a G Pro X when one is '
		                  'connected, otherwise your default microphone.', ['muted', 'small'], wrap=True))
		self.inputs = [('auto', 'Automatic')]
		self.dropdown = Gtk.DropDown.new_from_strings([d for _, d in self.inputs])
		self.dropdown.connect('notify::selected', self._on_input)
		card.append(self.dropdown)
		card.append(label('Headset', ['section-title']))
		card.append(label('G HUB tunes its Blue VO!CE presets per headset. Automatic chooses from the '
		                  'microphone in use.', ['muted', 'small'], wrap=True))
		self.models = [('auto', 'Automatic'), ('wired', 'G Pro X'), ('wireless', 'G Pro X Wireless')]
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
		sw.connect('notify::active', lambda *_: on_change(sw))
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
		self.append(page_header('My presets', 'Presets you saved. Logitech’s are on the Voice page.',
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
		dialog.save(self.win, None, done)

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
		dialog.open(self.win, None, done)


# --- window --------------------------------------------------------------------------------

class MainWindow(Adw.ApplicationWindow):
	PAGES = ['voice', 'effects', 'microphone', 'presets']

	def __init__(self, app, start_page='voice'):
		super().__init__(application=app, title='Blue VO!CE', default_width=1100, default_height=760)
		self.loading = False
		self._save_id = 0
		self.cfg = store.load_config()
		self.model = store.headset_model(self.cfg, store.read_status())
		self.ghub_presets = store.ghub_presets(self.model)
		self.base_params = copy.deepcopy(self.cfg['params'])  # what "Reset to preset" returns to

		self.toasts = Adw.ToastOverlay()
		outer = box()
		self.banner = Adw.Banner(title='Logitech’s Blue VO!CE files are missing. Run ./install.sh again.')
		self.banner.set_revealed(not os.path.exists(store.APO_DLL))
		outer.append(self.banner)
		root = box(Gtk.Orientation.HORIZONTAL, css=['app-bg'], vexpand=True)
		outer.append(root)
		self.toasts.set_child(outer)
		self.set_content(self.toasts)

		self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True)
		self.voice_page = VoicePage(self)
		self.effects_page = EffectsPage(self)
		self.mic_page = MicrophonePage(self)
		self.presets_page = PresetsPage(self)
		for page, name in ((self.voice_page, 'voice'), (self.effects_page, 'effects'),
		                   (self.mic_page, 'microphone'), (self.presets_page, 'presets')):
			self.stack.add_named(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=page), name)
		root.append(self._build_sidebar())
		root.append(self.stack)
		self.show_page(start_page if start_page in self.PAGES else 'voice')

		self._service_active = service.is_active()
		if not self._service_active and service.installed():
			threading.Thread(target=service.start, daemon=True).start()
		GLib.timeout_add(100, self._poll_status)
		GLib.timeout_add_seconds(3, self._poll_slow)

	def _build_sidebar(self):
		side = box(spacing=28, css=['sidebar'], width_request=232)
		side.set_hexpand(False)
		brand = box(Gtk.Orientation.HORIZONTAL, 10, halign=Gtk.Align.CENTER)
		icon = os.path.join(APP_DIR, 'lghub-bluevoice.svg')
		logo = Gtk.Image.new_from_file(icon) if os.path.exists(icon) else \
			Gtk.Image.new_from_icon_name('audio-input-microphone-symbolic')
		logo.set_pixel_size(32)
		brand.append(logo)
		brand.append(label('Blue VO!CE', ['brand-title'], valign=Gtk.Align.CENTER))
		side.append(brand)

		nav = box(spacing=4)
		self.nav_buttons = {}
		for key, text, icon_name in (
			('voice', 'Voice', 'audio-input-microphone-symbolic'),
			('effects', 'Effects', 'preferences-other-symbolic'),
			('microphone', 'Microphone', 'audio-card-symbolic'),
			('presets', 'My presets', 'view-list-symbolic'),
		):
			b = Gtk.Button()
			b.add_css_class('nav')
			content = box(Gtk.Orientation.HORIZONTAL, 12)
			content.append(Gtk.Image.new_from_icon_name(icon_name))
			content.append(label(text))
			b.set_child(content)
			b.connect('clicked', lambda _w, k=key: self.show_page(k))
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
		self.side_bar = meter_bar()
		self.side_value = label('', ['value', 'small'])
		card.append(self.side_bar)
		side.append(card)
		return side

	def show_page(self, key):
		self.stack.set_visible_child_name(key)
		for k, b in self.nav_buttons.items():
			(b.add_css_class if k == key else b.remove_css_class)('active')
		if key == 'microphone':
			self.mic_page.refresh_inputs()

	def toast(self, text):
		self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

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
		model = store.headset_model(self.cfg, status if status is not None else store.read_status())
		if model != self.model:
			self.model = model
			self.ghub_presets = store.ghub_presets(model)
			self.voice_page.load()

	# --- status --------------------------------------------------------------------------

	def _poll_status(self):
		status = store.read_status()
		fresh = status.get('updated', 0) > GLib.get_real_time() / 1e6 - 3
		if not fresh:
			status = {'state': 'stopped'}
		state = status.get('state')
		if self.cfg.get('headset', 'auto') == 'auto' and status.get('input'):
			self.refresh_model(status)
		self.voice_page.update_status(status)
		self.mic_page.update_status(status, self._service_active)
		for c in ('ok', 'warn', 'err', 'muted'):
			self.conn_label.remove_css_class(c)
		word, dot, css = {
			'running': ('Active', '● Running', 'ok'),
			'starting': ('Starting', '● Starting', 'warn'),
			'error': ('Problem', '● Error', 'err'),
		}.get(state, ('Off', '● Stopped', 'muted'))
		if state == 'running' and not status.get('listening', True):
			word = 'Standby'
		elif state == 'running' and not status.get('enabled', True):
			word = 'Bypassed'
		self.side_state.set_text(word)
		self.conn_label.set_text(dot)
		self.conn_label.add_css_class(css)
		inp = status.get('input')
		if state == 'running' and not status.get('listening', True):
			self.side_input.set_text('Ready. Your microphone opens when an app uses Blue VO!CE.')
		elif state == 'running':
			self.side_input.set_text(f"From {inp['description']}" if inp else 'Waiting for a microphone')
		elif state == 'error':
			self.side_input.set_text(status.get('error', ''))
		else:
			self.side_input.set_text('')
		self.side_bar.set_value(max(0.0, status.get('meter_out', -120) + 60) if state == 'running' else 0)
		return True

	def _poll_slow(self):
		def work():
			active = service.is_active()
			GLib.idle_add(setattr, self, '_service_active', active)
		threading.Thread(target=work, daemon=True).start()
		return True


class App(Adw.Application):
	def __init__(self):
		super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

	def do_startup(self):
		Adw.Application.do_startup(self)
		Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
		provider = Gtk.CssProvider()
		provider.load_from_string(CSS)
		Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
		                                          Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

	def do_activate(self):
		page = 'voice'
		argv = sys.argv
		if '--page' in argv and argv.index('--page') + 1 < len(argv):
			page = argv[argv.index('--page') + 1]
		win = self.props.active_window or MainWindow(self, page)
		win.present()
		if '--screenshot' in argv and argv.index('--screenshot') + 1 < len(argv):
			path = argv[argv.index('--screenshot') + 1]
			GLib.timeout_add(2500, self._screenshot, win, path)

	def _screenshot(self, win, path):
		"""Render the window itself to a PNG (for the README); independent of the screen."""
		paintable = Gtk.WidgetPaintable.new(win)
		snapshot = Gtk.Snapshot()
		paintable.snapshot(snapshot, win.get_width(), win.get_height())
		node = snapshot.to_node()
		if node:
			win.get_renderer().render_texture(node, None).save_to_png(path)
		self.quit()
		return False


if __name__ == '__main__':
	App().run(None)
