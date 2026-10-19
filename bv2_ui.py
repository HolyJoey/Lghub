"""Blue VO!CE 2 page for the Yetis and the G735: on/off, G HUB's presets for the device, and a
switch per stage of the chain. Like the Blue VO!CE page it only edits config.json (bv2_params,
bv2_preset) and shows status.json; the engine runs the DSP."""
from gi.repository import GLib, Gtk

import bv2_presets
import depots
import store
from headset_ui import switch_row
from ui import box, label, meter_bar, page_header, set_meter
from worker import Worker

NOTIFY_ACTIVE = 'notify::active'


class Bv2Page(Gtk.Box):
	def __init__(self, win, device):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.model = device.model.key
		self.loading = False
		self.presets = []
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

		self.append(label('Presets', ['section-title']))
		self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=10, row_spacing=10,
		                        min_children_per_line=2, max_children_per_line=6, homogeneous=True)
		self.append(self.flow)
		self.preset_note = label('Fetching G HUB’s presets for this microphone…', ['muted', 'small'])
		self.append(self.preset_note)
		self.preset_buttons = {}

		self.append(label('Stages', ['section-title']))
		stages = box(spacing=14, css=['card'])
		self.stage_switches = {}
		for _section, name in bv2_presets.SECTIONS:
			key = bv2_presets.switch_for(name)
			self.stage_switches[key] = switch_row(stages, name, None, False,
			                                      lambda on, k=key: self._on_stage(k, on))
		self.append(stages)

		self.worker = Worker()
		self.worker.submit(lambda: depots.fetch_bv2_presets(self.model), self._got_presets,
		                   lambda _e: self._got_presets(None))
		self._load_config()
		self._timer = GLib.timeout_add(200, self._poll)

	def close(self):
		if self._timer:
			GLib.source_remove(self._timer)
			self._timer = 0
		self.worker.stop()

	# --- presets ---------------------------------------------------------------------------

	def _got_presets(self, path):
		self.presets = bv2_presets.load(path) if path else []
		if not self.presets:
			self.preset_note.set_text('No G HUB presets for this microphone yet; it runs on the DSP’s own defaults.')
			return
		self.preset_note.set_visible(False)
		for pid, name, _settings in self.presets:
			b = Gtk.Button(label=name)
			b.add_css_class('preset')
			b.set_size_request(-1, 44)
			b.connect('clicked', lambda _w, p=pid: self._choose(p))
			self.flow.append(b)
			self.preset_buttons[pid] = b
		self._load_config()

	def _choose(self, pid):
		settings = next(s for p, _n, s in self.presets if p == pid)
		cfg = store.load_config()
		cfg['bv2_preset'] = pid
		cfg['bv2_params'] = dict(settings)
		store.save_config(cfg)
		self._load_config()

	# --- switches --------------------------------------------------------------------------

	def _on_switch(self, *_):
		if self.loading:
			return
		cfg = store.load_config()
		cfg['enabled'] = self.switch.get_active()
		store.save_config(cfg)
		self._load_config()

	def _on_stage(self, key, on):
		if self.loading:
			return
		cfg = store.load_config()
		params = dict(cfg.get('bv2_params', {}))
		params[key] = 1 if on else 0
		cfg['bv2_params'] = params
		store.save_config(cfg)

	def _load_config(self):
		cfg = store.load_config()
		self.loading = True
		self.switch.set_active(cfg.get('enabled', True))
		self.state_word.set_text('On' if cfg.get('enabled', True) else 'Off')
		params = cfg.get('bv2_params', {})
		for key, sw in self.stage_switches.items():
			sw.set_active(bool(params.get(key, 0)))
			sw.set_sensitive(bool(params))     # the DSP's defaults aren't G HUB settings to switch
		chosen = cfg.get('bv2_preset')
		for pid, b in self.preset_buttons.items():
			if pid == chosen:
				b.add_css_class('suggested-action')
			else:
				b.remove_css_class('suggested-action')
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
