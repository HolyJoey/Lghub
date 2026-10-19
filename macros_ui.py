"""The Macros page: the user's macro library, in G HUB's macro format (see macros.py). Sequences
are recorded from the keyboard, with their timing, like G HUB's macro recorder."""
import time

from gi.repository import GLib, Gdk, Gtk

import macros
from ui import box, button_widget, label, page_header

TYPES = (('SEQUENCE', 'Recorded sequence'), ('KEYSTROKE', 'Keystroke'), ('TEXT_BLOCK', 'Text'),
         ('MEDIA', 'Media key'), ('SYSTEM', 'System action'), ('APP', 'Launch an app'),
         ('OPEN_WEB_PAGE', 'Open a web page'), ('AUDIO', 'Audio'))
MODES = (('once', 'Play once'), ('held', 'Repeat while held'), ('toggle', 'Start / stop on each press'))
MEDIA = tuple(macros.MEDIA)
SYSTEM = tuple(sorted(set(macros.SYSTEM_KEYS) | set(macros.SYSTEM_CONSUMER) | set(macros.SYSTEM_COMMANDS)))
AUDIO = tuple(macros.AUDIO_COMMANDS)
MODIFIER_NAMES = {'Control_L': 0xe0, 'Shift_L': 0xe1, 'Alt_L': 0xe2, 'Super_L': 0xe3, 'Control_R': 0xe4,
                  'Shift_R': 0xe5, 'Alt_R': 0xe6, 'ISO_Level3_Shift': 0xe6, 'Super_R': 0xe7}


def nice(action):
	return action.replace('_', ' ').capitalize()


def keyval_usage(keyval):
	"""HID usage of a GDK key, modifiers included, or None."""
	import mouse_ui   # the keyboard table lives with the mouse's keystroke recorder
	name = Gdk.keyval_name(keyval) or ''
	return MODIFIER_NAMES.get(name) or mouse_ui.hid_usage(keyval)


def dropdown(options, selected=None):
	dd = Gtk.DropDown.new_from_strings([text for _key, text in options])
	keys = [key for key, _text in options]
	if selected in keys:
		dd.set_selected(keys.index(selected))
	return dd, keys


OWN_ACTION = 'Its own action'


class MacrosPage(Gtk.Box):
	"""buttons: [(key, label)] of the device's assignable buttons, e.g. ("button:6", "Button 6") or
	("gkey:1", "G1"); with a device, a card puts macros on them (run by the background service)."""

	def __init__(self, win, device=None, buttons=()):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.device = device
		self.buttons = list(buttons)
		self.bank = 1           # M-key set shown for G-keys (G HUB's M1-M3)
		self.append(page_header('Macros', 'Keystrokes, recorded sequences, text, apps and more, ready to put on a '
		                        'button.', button_widget('New macro', ['apply'], lambda: self._edit(None))))
		self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
		self.list.add_css_class('plain')
		self.append(self.list)
		self.empty = label('No macros yet.', ['muted'])
		self.append(self.empty)
		self.assign_card = box(spacing=10, css=['card'])
		if device and self.buttons:
			self.append(self.assign_card)
		self.load()

	def load(self):
		while (row := self.list.get_first_child()):
			self.list.remove(row)
		lib = macros.library()
		self.empty.set_visible(not lib)
		for mid, m in sorted(lib.items(), key=lambda kv: kv[1].get('name', '').lower()):
			r = box(Gtk.Orientation.HORIZONTAL, 10)
			titles = box(spacing=2, hexpand=True)
			titles.append(label(m.get('name') or 'Macro', ['preset-name']))
			kind = dict(TYPES).get(m.get('type'), m.get('type', ''))
			titles.append(label(f'{kind} · {macros.describe(m)}' if m.get('type') != 'SEQUENCE' else kind,
			                    ['muted', 'small']))
			r.append(titles)
			r.append(button_widget('Edit', ['ghost'], lambda i=mid: self._edit(i)))
			r.append(button_widget('Delete', ['danger'], lambda i=mid: self._delete(i)))
			self.list.append(r)
		self._assignments(lib)

	def _assignments(self, lib):
		import inputd
		while (child := self.assign_card.get_first_child()):
			self.assign_card.remove(child)
		if not (self.device and self.buttons):
			return
		self.assign_card.append(label('On buttons', ['section-title']))
		self.assign_card.append(label('A button with a macro runs it instead of its own action. The background '
		                              'service does this, so it works with the app closed.', ['muted', 'small'],
		                              wrap=True))
		ids = [None] + sorted(lib, key=lambda i: lib[i].get('name', '').lower())
		names = [OWN_ACTION] + [lib[i].get('name') or 'Macro' for i in ids[1:]]
		current = macros.assignments().get(inputd.ident(self.device), {})
		if any(key.startswith('gkey:') for key, _text in self.buttons):
			sets = Gtk.DropDown.new_from_strings(['M1', 'M2', 'M3'])
			sets.set_selected(self.bank - 1)
			sets.connect('notify::selected', lambda w, _p: self._show_bank(w.get_selected() + 1, lib))
			r = box(Gtk.Orientation.HORIZONTAL, 16)
			r.append(label('G-key set (switched with the M-keys)', ['muted'], hexpand=True, valign=Gtk.Align.CENTER))
			r.append(sets)
			self.assign_card.append(r)
		for key, text in self.buttons:
			if key.startswith('gkey:'):
				key = inputd.gkey_name(self.bank, int(key.split(':')[1]))
			dd = Gtk.DropDown.new_from_strings(names)
			dd.set_selected(ids.index(current.get(key)) if current.get(key) in ids else 0)
			dd.connect('notify::selected', lambda w, _p, k=key: self._assign(k, ids[w.get_selected()]))
			r = box(Gtk.Orientation.HORIZONTAL, 16)
			r.append(label(text, ['muted'], hexpand=True, valign=Gtk.Align.CENTER))
			r.append(dd)
			self.assign_card.append(r)

	def _show_bank(self, bank, lib):
		self.bank = bank
		GLib.idle_add(lambda: self._assignments(lib) and False)

	def _assign(self, key, mid):
		import inputd
		data = macros.assignments()
		mine = data.setdefault(inputd.ident(self.device), {})
		if mid:
			mine[key] = mid
		else:
			mine.pop(key, None)
		macros.save_assignments(data)

	def _delete(self, mid):
		lib = macros.library()
		name = lib.pop(mid, {}).get('name', 'Macro')
		macros.save_library(lib)
		self.load()
		self.win.toast(f'Deleted “{name}”')

	def _edit(self, mid):
		lib = macros.library()
		MacroEditor(self.get_root(), lib.get(mid), lambda m: self._saved(mid, m)).present()

	def _saved(self, mid, macro):
		lib = macros.library()
		lib[mid or macros.new_id(lib)] = macro
		macros.save_library(lib)
		self.load()
		self.win.toast(f'Saved “{macro.get("name", "Macro")}”')


class MacroEditor(Gtk.Window):
	def __init__(self, parent, macro, on_save):
		super().__init__(title='Macro', modal=True, transient_for=parent, default_width=520, default_height=440)
		self.on_save = on_save
		self.macro = dict(macro or {'type': 'SEQUENCE', 'name': ''})
		self.events = []
		self.recording = False
		content = box(spacing=14, css=['page'])
		self.name = Gtk.Entry(text=self.macro.get('name', ''), placeholder_text='Name')
		content.append(self.name)
		self.type_dd, self.type_keys = dropdown(TYPES, self.macro.get('type'))
		self.type_dd.connect('notify::selected', lambda *_: self._show_fields())
		content.append(self.type_dd)
		self.fields = box(spacing=10, vexpand=True)
		content.append(self.fields)
		buttons = box(Gtk.Orientation.HORIZONTAL, 10, halign=Gtk.Align.END)
		buttons.append(button_widget('Cancel', ['ghost'], self.close))
		buttons.append(button_widget('Save', ['apply'], self._save))
		content.append(buttons)
		self.set_child(content)
		keys = Gtk.EventControllerKey()
		keys.connect('key-pressed', lambda _c, kv, _code, st: self._key(kv, st, True))
		keys.connect('key-released', lambda _c, kv, _code, st: self._key(kv, st, False))
		self.add_controller(keys)
		self._show_fields()

	@property
	def kind(self):
		return self.type_keys[self.type_dd.get_selected()]

	def _clear(self):
		while (child := self.fields.get_first_child()):
			self.fields.remove(child)

	def _show_fields(self):
		self._clear()
		self.recording = False
		builder = {'SEQUENCE': self._sequence_fields, 'KEYSTROKE': self._keystroke_fields,
		           'TEXT_BLOCK': lambda: self._entry_field('text_block', 'text', 'Text to type'),
		           'APP': lambda: self._entry_field('app', 'executable_path', 'Command, e.g. firefox'),
		           'OPEN_WEB_PAGE': lambda: self._entry_field('open_web_page', 'url', 'https://…'),
		           'MEDIA': lambda: self._choice_field('media', 'usage', MEDIA),
		           'SYSTEM': lambda: self._choice_field('system', 'action', SYSTEM),
		           'AUDIO': lambda: self._choice_field('audio', 'action', AUDIO)}
		builder[self.kind]()

	def _entry_field(self, part, key, hint):
		self.entry = Gtk.Entry(text=self.macro.get(part, {}).get(key, ''), placeholder_text=hint)
		self.fields.append(self.entry)

	def _choice_field(self, part, key, choices):
		self.choice, self.choice_keys = dropdown([(c, nice(c)) for c in choices], self.macro.get(part, {}).get(key))
		self.fields.append(self.choice)

	def _keystroke_fields(self):
		self.fields.append(label('Press the key combination now.', ['muted'], wrap=True))
		k = self.macro.get('keystroke')
		self.combo_label = label(macros.describe(self.macro) if k else '…', ['big-word'])
		self.fields.append(self.combo_label)
		self.recording = True

	def _sequence_fields(self):
		seq = self.macro.get('sequence', {})
		mode = 'once'
		if seq.get('use_toggle_actions'):
			mode = 'toggle'
		elif seq.get('use_repeat_actions'):
			mode = 'held'
		self.mode_dd, self.mode_keys = dropdown(MODES, mode)
		self.fields.append(self.mode_dd)
		r = box(Gtk.Orientation.HORIZONTAL, 12)
		r.append(label('Record the pauses between keys', hexpand=True, valign=Gtk.Align.CENTER))
		self.delays = Gtk.Switch(active=not seq.get('use_default_delay', False), valign=Gtk.Align.CENTER)
		r.append(self.delays)
		self.fields.append(r)
		self.record_button = button_widget('Start recording', ['ghost'], self._toggle_recording)
		self.fields.append(self.record_button)
		self.steps = label(self._steps_text(), ['muted', 'small'], wrap=True)
		self.fields.append(self.steps)

	def _steps_text(self):
		if self.events:
			downs = [macros.key_name(u) for u, d, _t in self.events if d]
			return f'{len(downs)} keys: ' + ' '.join(downs[:30])
		comps = macros.sequence_components(self.macro)
		keys = [macros.key_name(c['keyboard']['hid_usage']) for c in comps
		        if 'keyboard' in c and c['keyboard'].get('is_down')]
		return f'{len(keys)} keys: ' + ' '.join(keys[:30]) if keys else 'Nothing recorded yet.'

	def _toggle_recording(self):
		self.recording = not self.recording
		if self.recording:
			self.events = []
		self.record_button.set_label('Stop recording' if self.recording else 'Record again')
		self.steps.set_text('Recording… type the keys.' if self.recording else self._steps_text())

	def _key(self, keyval, state, down):
		if not self.recording:
			return False
		usage = keyval_usage(keyval)
		if usage is None:
			return True
		if self.kind == 'KEYSTROKE':
			if down and usage not in macros.uinput.MODIFIER_USAGES:
				mods = [u for mask, u in ((Gdk.ModifierType.CONTROL_MASK, 0xe0), (Gdk.ModifierType.SHIFT_MASK, 0xe1),
				                          (Gdk.ModifierType.ALT_MASK, 0xe2), (Gdk.ModifierType.SUPER_MASK, 0xe3))
				        if state & mask]
				self.macro['keystroke'] = {'code': usage, 'modifiers': mods}
				self.macro['type'] = 'KEYSTROKE'
				self.combo_label.set_text(macros.describe(self.macro))
			return True
		self.events.append((usage, down, time.monotonic()))
		return True

	def _save(self):
		kind = self.kind
		name = self.name.get_text().strip() or dict(TYPES)[kind]
		if kind == 'SEQUENCE':
			if self.events:
				m = macros.recorded_sequence(self.events, self.delays.get_active(),
				                             self.mode_keys[self.mode_dd.get_selected()])
			elif 'sequence' in self.macro:   # same recording, maybe another mode
				m = macros.sequence_macro(macros.sequence_components(self.macro), self.delays.get_active(),
				                          self.mode_keys[self.mode_dd.get_selected()])
			else:
				return
		elif kind == 'KEYSTROKE':
			if 'keystroke' not in self.macro:
				return
			m = {'type': kind, 'keystroke': self.macro['keystroke']}
		elif kind in ('TEXT_BLOCK', 'APP', 'OPEN_WEB_PAGE'):
			part, key = {'TEXT_BLOCK': ('text_block', 'text'), 'APP': ('app', 'executable_path'),
			             'OPEN_WEB_PAGE': ('open_web_page', 'url')}[kind]
			m = {'type': kind, part: {key: self.entry.get_text()}}
		else:
			part, key = {'MEDIA': ('media', 'usage'), 'SYSTEM': ('system', 'action'), 'AUDIO': ('audio', 'action')}[kind]
			m = {'type': kind, part: {key: self.choice_keys[self.choice.get_selected()]}}
		m['name'] = name
		self.on_save(m)
		self.close()
