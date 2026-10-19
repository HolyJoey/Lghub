"""Blue VO!CE 2 page for the Yetis and the G735: on/off, G HUB's presets for the device, every stage
with G HUB's controls, and the voice effects (G HUB's effect presets, voice changer, chorus,
flanger, reverb, delay, ring modulator). Like the Blue VO!CE page it only edits config.json
(bv2_params, bv2_preset, bv2_effects_preset) and shows status.json; the engine runs the DSP."""
from gi.repository import GLib, Gtk

import bv2_presets
import depots
import store
from ui import box, format_value, label, meter_bar, page_header, set_meter
from worker import Worker

NOTIFY_ACTIVE = 'notify::active'
SAVE_DELAY_MS = 150


def _text(value, unit):
	if unit == 'cents':
		return f'{value:+.0f} cents'
	if unit == 'Q':
		return f'Q {value:.2f}'
	if unit == 'gain':
		return f'{value * 100:.0f} %'
	if unit == 'Hz' and value < 10:
		return f'{value:.2f} Hz'
	return format_value(value, unit)


class Bv2Page(Gtk.Box):
	def __init__(self, win, device):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.model = device.model.key
		self.loading = False
		self.params = {}
		self.controls = {}      # setting -> (kind, widget, value label or choices, unit)
		self.switches = {}      # switch setting -> (switch, card)
		self._save_id = 0
		self.append(page_header('Blue VO!CE', 'Blue VO!CE 2, the voice chain G HUB runs on this microphone. '
		                        'Changes apply live.'))

		hero = box(Gtk.Orientation.HORIZONTAL, 20, ['card', 'hero'])
		left = box(spacing=6, hexpand=True)
		left.append(label('Blue VO!CE', ['muted', 'small']))
		self.state_word = label('', ['big-word'])
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

		self.voice = self._preset_block('Presets', 'Fetching G HUB’s presets for this microphone…')
		self.note = label('Pick a preset to start from; until then the DSP runs on its own defaults.',
		                  ['muted', 'small'], wrap=True)
		self.append(self.note)
		for title, switch, controls in bv2_presets.STAGES:
			self.append(self._stage_card(title, switch, controls))

		self.effects = self._preset_block('Voice effects', '')
		for title, switch, controls in bv2_presets.EFFECT_STAGES:
			self.append(self._stage_card(title, switch, controls))

		self.worker = Worker()
		self.worker.submit(lambda: depots.fetch_bv2_presets(self.model), self._got_presets,
		                   lambda _e: self._got_presets(None))
		self._load_config()
		self._timer = GLib.timeout_add(200, self._poll)

	def close(self):
		if self._timer:
			GLib.source_remove(self._timer)
			self._timer = 0
		if self._save_id:
			GLib.source_remove(self._save_id)
			self._save()
		self.worker.stop()

	# --- building --------------------------------------------------------------------------

	def _preset_block(self, title, note):
		self.append(label(title, ['section-title']))
		flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10,
		                   min_children_per_line=2, max_children_per_line=6, homogeneous=True)
		self.append(flow)
		note_label = label(note, ['muted', 'small'])
		note_label.set_visible(bool(note))
		self.append(note_label)
		return {'flow': flow, 'note': note_label, 'buttons': {}, 'presets': []}

	def _stage_card(self, title, switch, controls):
		card = box(spacing=10, css=['card'])
		head = box(Gtk.Orientation.HORIZONTAL, 16)
		head.append(label(title, ['stage-title'], hexpand=True))
		if switch:
			sw = Gtk.Switch(valign=Gtk.Align.CENTER)
			sw.connect(NOTIFY_ACTIVE, lambda w, _p, s=switch: self._on_stage(s, w))
			head.append(sw)
			self.switches[switch] = (sw, card)
		card.append(head)
		for spec in controls:
			row = box(Gtk.Orientation.HORIZONTAL, 14)
			row.append(label(spec[1], ['muted'], width_chars=20))
			if len(spec) == 3:      # a choice: G HUB's enum
				options = bv2_presets.choices(spec[2])
				dd = Gtk.DropDown.new_from_strings([text for _n, text in options])
				dd.set_hexpand(True)
				dd.connect('notify::selected', lambda w, _p, s=spec[0]: self._on_choice(s, w))
				row.append(dd)
				self.controls[spec[0]] = ('choice', dd, options, None)
			else:
				name, _text_label, lo, hi, step, unit = spec
				scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
				scale.set_hexpand(True)
				scale.set_draw_value(False)
				value = label('', ['value'], width_chars=11, xalign=1.0)
				scale.connect('value-changed', lambda w, s=name, u=unit, v=value: self._on_scale(s, u, w, v))
				row.append(scale)
				row.append(value)
				self.controls[name] = ('scale', scale, value, unit)
			card.append(row)
		return card

	# --- presets ---------------------------------------------------------------------------

	def _got_presets(self, path):
		for block, effects in ((self.voice, False), (self.effects, True)):
			block['presets'] = bv2_presets.load(path, effects) if path else []
			block['note'].set_visible(not block['presets'])
			block['note'].set_text('No G HUB presets for this microphone.')
			for pid, name, _settings in block['presets']:
				b = Gtk.Button(label=name)
				b.add_css_class('preset')
				b.set_size_request(-1, 44)
				b.connect('clicked', lambda _w, p=pid, e=effects: self._choose(p, e))
				block['flow'].append(b)
				block['buttons'][pid] = b
		self._load_config()

	def _choose(self, pid, effects):
		block = self.effects if effects else self.voice
		settings = next(s for p, _n, s in block['presets'] if p == pid)
		self._flush()
		cfg = store.load_config()
		cfg['bv2_effects_preset' if effects else 'bv2_preset'] = pid
		cfg['bv2_params'] = {**cfg.get('bv2_params', {}), **settings}
		store.save_config(cfg)
		self._load_config()

	# --- changes ---------------------------------------------------------------------------

	def _on_switch(self, *_):
		if self.loading:
			return
		self._flush()
		cfg = store.load_config()
		cfg['enabled'] = self.switch.get_active()
		store.save_config(cfg)
		self._load_config()

	def _on_stage(self, name, sw):
		card = self.switches[name][1]
		(card.remove_css_class if sw.get_active() else card.add_css_class)('off')
		if not self.loading:
			self._set(name, 1 if sw.get_active() else 0)

	def _on_scale(self, name, unit, scale, value):
		value.set_text(_text(scale.get_value(), unit))
		if not self.loading:
			self._set(name, round(scale.get_value(), 4))

	def _on_choice(self, name, dropdown):
		if not self.loading:
			options = self.controls[name][2]
			self._set(name, options[dropdown.get_selected()][0])

	def _set(self, name, value):
		"""Change one setting; written to config.json shortly after the last change."""
		self.params[name] = value
		if self._save_id:
			GLib.source_remove(self._save_id)
		self._save_id = GLib.timeout_add(SAVE_DELAY_MS, self._save)

	def _flush(self):
		if self._save_id:
			GLib.source_remove(self._save_id)
			self._save()

	def _save(self):
		self._save_id = 0
		cfg = store.load_config()
		cfg['bv2_params'] = {**cfg.get('bv2_params', {}), **self.params}
		store.save_config(cfg)
		return False

	def _load_config(self):
		cfg = store.load_config()
		self.params = dict(cfg.get('bv2_params', {}))
		self.loading = True
		enabled = cfg.get('enabled', True)
		self.switch.set_active(enabled)
		self.state_word.set_text('On' if enabled else 'Off')
		chosen = bool(set(self.params) & set(bv2_presets.VOICE_NAMES))
		self.note.set_visible(not chosen)
		for name, (kind, widget, extra, unit) in self.controls.items():
			value = self.params.get(name, 0)
			if kind == 'choice':
				widget.set_selected(next((i for i, (n, _t) in enumerate(extra) if n == value), 0))
			else:
				widget.set_value(value)
				extra.set_text(_text(widget.get_value(), unit))
			widget.set_sensitive(name in self.params)   # the DSP's own defaults aren't known values
		for name, (sw, card) in self.switches.items():
			on = bool(self.params.get(name, 0))
			sw.set_active(on)
			sw.set_sensitive(name in self.params)
			(card.remove_css_class if on else card.add_css_class)('off')
		for block, key in ((self.voice, 'bv2_preset'), (self.effects, 'bv2_effects_preset')):
			for pid, b in block['buttons'].items():
				(b.add_css_class if pid == cfg.get(key) else b.remove_css_class)('suggested-action')
		self.loading = False

	# --- status ----------------------------------------------------------------------------

	def _poll(self):
		status = store.read_status() or {}
		ready = status.get('state') == 'running' and status.get('voice') == 'bv2'
		set_meter(*self.bars['in'], status.get('meter_in', -120) if ready else -120)
		set_meter(*self.bars['out'], status.get('meter_out', -120) if ready else -120)
		inp = status.get('input') or {}
		if status.get('voice') == 'bv2':
			text = f'{inp.get("description", "Microphone")} → Blue VO!CE Microphone'
		elif status.get('state') == 'error':
			text = status.get('error') or 'Problem: see journalctl --user -u lghub-bluevoice'
		else:
			text = 'Waiting for the microphone (the engine picks it up when it is plugged in)'
		if text != self.route.get_text():   # a wrapping label relayouts on every set_text
			self.route.set_text(text)
		return True
