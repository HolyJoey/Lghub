"""Macros, stored and run the way G HUB defines them (logi.protocol.macros.Macro in G HUB's own
schema), kept as JSON with the same field names. Supported types: KEYSTROKE, TEXT_BLOCK, MOUSE,
MEDIA, SYSTEM, APP, OPEN_WEB_PAGE, AUDIO and SEQUENCE (simple, press/held/release and toggle
sequences of keys, mouse events and delays). DPI and profile actions go to the mouse (inputd.
DeviceActions); a G-Shift button switches the other buttons to their G-Shift layer (inputd).

A Runner presses and releases macros as their button goes down and up; long sequences run on
their own thread so a button press never blocks.
"""
import subprocess
import threading
import time

import uinput

MEDIA = {'PLAY_PAUSE': 0xcd, 'STOP': 0xb7, 'VOLUME_UP': 0xe9, 'VOLUME_DOWN': 0xea, 'NEXT_TRACK': 0xb5,
         'PREVIOUS_TRACK': 0xb6, 'MUTE': 0xe2}
CTRL, SHIFT, ALT, SUPER = 0xe0, 0xe1, 0xe2, 0xe3
# SYSTEM actions as the key combinations Linux desktops use for them
SYSTEM_KEYS = {'COPY': (CTRL, 0x06), 'PASTE': (CTRL, 0x19), 'UNDO': (CTRL, 0x1d), 'REDO': (CTRL, SHIFT, 0x1d),
               'CLOSE': (ALT, 0x3d), 'ZOOM_IN': (CTRL, 0x2e), 'ZOOM_OUT': (CTRL, 0x2d),
               'SWITCH_APPS': (ALT, 0x2b), 'SHIFT_SWITCH_APPS': (ALT, SHIFT, 0x2b), 'DESKTOP': (SUPER, 0x07),
               'SHOW_DESKTOP': (SUPER, 0x07), 'SCREEN_CAPTURE': (0x46,), 'APP_MENU': (0x65,),
               'MAXIMIZE': (SUPER, 0x52), 'MINIMIZE': (SUPER, 0x0b), 'SNAP_LEFT': (SUPER, 0x50),
               'SNAP_RIGHT': (SUPER, 0x4f), 'FULLSCREEN': (0x44,)}
SYSTEM_CONSUMER = {'BRIGHTNESS_UP': 0x6f, 'BRIGHTNESS_DOWN': 0x70, 'MAIL_CLIENT': 0x18a,
                   'INTERNET_CLIENT': 0x223, 'FILE_CLIENT': 0x194}
SYSTEM_COMMANDS = {'LOCK': ['loginctl', 'lock-session']}
WHEEL = {'WHEEL_UP': (1, False), 'WHEEL_DOWN': (-1, False), 'WHEEL_LEFT': (-1, True), 'WHEEL_RIGHT': (1, True)}
# Sequence steps that are whole macros of their own
COMPONENT_MACROS = ('keystroke', 'text_block', 'media', 'system', 'app', 'audio', 'open_web_page', 'device')
DEVICE_ACTIONS = {('MOUSE', 'DPI_UP'), ('MOUSE', 'DPI_DOWN'), ('MOUSE', 'DPI_SHIFT'), ('MOUSE', 'DPI_CYCLE'),
                  ('MOUSE', 'DPI_DEFAULT'), ('DEVICE', 'PROFILE_CYCLE'), ('DEVICE', 'PROFILE_NEXT'),
                  ('DEVICE', 'PROFILE_PREV'), ('DEVICE', 'G_SHIFT')}

# Typing text on a US layout: character -> (shift, usage)
_US_SHIFTED = dict(zip('!@#$%^&*()_+{}|:"~<>?', (0x1e, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x2d,
                                                 0x2e, 0x2f, 0x30, 0x31, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38)))
_US_PLAIN = dict(zip('-=[]\\;\'`,./ \n\t', (0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x2c,
                                             0x28, 0x2b)))


def char_usage(ch):
	"""(shift, HID usage) for typing ch on a US layout, or None."""
	if 'a' <= ch <= 'z':
		return False, 0x04 + ord(ch) - ord('a')
	if 'A' <= ch <= 'Z':
		return True, 0x04 + ord(ch) - ord('A')
	if '1' <= ch <= '9':
		return False, 0x1e + ord(ch) - ord('1')
	if ch == '0':
		return False, 0x27
	if ch in _US_PLAIN:
		return False, _US_PLAIN[ch]
	if ch in _US_SHIFTED:
		return True, _US_SHIFTED[ch]
	return None


def is_device_action(macro):
	t = macro.get('type')
	return t == 'DEVICE' or t == 'MOUSE' and ('MOUSE', macro.get('mouse', {}).get('action')) in DEVICE_ACTIONS


def keystroke(code, modifiers=()):
	return {'type': 'KEYSTROKE', 'keystroke': {'code': code, 'modifiers': list(modifiers)}}


def describe(macro):
	"""A short label for a macro, as the button list shows it."""
	t = macro.get('type')
	if t == 'KEYSTROKE':
		k = macro['keystroke']
		mods = [uinput.MODIFIER_USAGES.get(m, '?') for m in k.get('modifiers', [])]
		return ' + '.join(mods + [key_name(k.get('code', 0))])
	if t == 'TEXT_BLOCK':
		return f"Type “{macro['text_block'].get('text', '')[:20]}”"
	if t == 'MEDIA':
		return macro['media'].get('usage', '').replace('_', ' ').capitalize()
	if t in ('MOUSE', 'SYSTEM', 'AUDIO', 'DEVICE'):
		action = macro[t.lower()].get('action', '')
		if t == 'MOUSE' and action == 'BUTTON':
			return f"Mouse button {macro['mouse'].get('hid_usage', 1)}"
		return action.replace('_', ' ').capitalize()
	if t == 'APP':
		return f"Run {macro['app'].get('executable_path', '')}"
	if t == 'OPEN_WEB_PAGE':
		return f"Open {macro['open_web_page'].get('url', '')}"
	if t == 'SEQUENCE':
		return macro.get('name') or 'Macro'
	return 'Disabled' if t in (None, 'INVALID') else t.replace('_', ' ').capitalize()


def key_name(usage):
	if 0x04 <= usage <= 0x1d:
		return chr(ord('A') + usage - 0x04)
	if 0x1e <= usage <= 0x26:
		return str(usage - 0x1d)
	if usage == 0x27:
		return '0'
	if 0x3a <= usage <= 0x45:
		return f'F{usage - 0x39}'
	if 0x68 <= usage <= 0x73:
		return f'F{usage - 0x5b}'
	names = {0x28: 'Enter', 0x29: 'Esc', 0x2a: 'Backspace', 0x2b: 'Tab', 0x2c: 'Space', 0x46: 'Print Screen',
	         0x49: 'Insert', 0x4a: 'Home', 0x4b: 'Page Up', 0x4c: 'Delete', 0x4d: 'End', 0x4e: 'Page Down',
	         0x4f: 'Right', 0x50: 'Left', 0x51: 'Down', 0x52: 'Up', 0x65: 'Menu'}
	return names.get(usage, uinput.MODIFIER_USAGES.get(usage, f'Key 0x{usage:02x}'))


class Runner:
	"""Plays macros on a virtual input device. device_action(kind, action, down) handles DPI and
	profile actions for the device the button belongs to (called on press, and on release too
	for the MOUSE ones, so DPI shift can end)."""

	def __init__(self, out=None, device_action=None):
		self.out = out
		self.device_action = device_action or (lambda _kind, _action, _down: None)
		self.toggles = {}          # button -> stop event of a running toggle sequence
		self.held = {}             # button -> stop event of a running held sequence

	def _out(self):
		if self.out is None:
			self.out = uinput.VirtualInput()
		return self.out

	def press(self, button, macro):
		t = macro.get('type')
		if t == 'SEQUENCE':
			self._sequence_press(button, macro['sequence'])
		elif t == 'KEYSTROKE':
			k = macro['keystroke']
			for m in k.get('modifiers', []):
				self._out().usage(m, True)
			self._out().usage(k.get('code', 0), True)
		elif t == 'MEDIA':
			self._out().usage(MEDIA.get(macro['media'].get('usage'), 0), True, consumer=True)
		elif t == 'MOUSE':
			self._mouse(macro['mouse'], True)
		else:
			self._once(macro)

	def release(self, button, macro):
		t = macro.get('type')
		if t == 'SEQUENCE':
			self._sequence_release(button, macro['sequence'])
		elif t == 'KEYSTROKE':
			k = macro['keystroke']
			self._out().usage(k.get('code', 0), False)
			for m in reversed(k.get('modifiers', [])):
				self._out().usage(m, False)
		elif t == 'MEDIA':
			self._out().usage(MEDIA.get(macro['media'].get('usage'), 0), False, consumer=True)
		elif t == 'MOUSE':
			self._mouse(macro['mouse'], False)

	# --- one-shot actions -----------------------------------------------------------------

	def _once(self, macro):
		t = macro.get('type')
		if t == 'TEXT_BLOCK':
			self.type_text(macro['text_block'].get('text', ''))
		elif t == 'SYSTEM':
			self._system(macro['system'].get('action'))
		elif t == 'APP':
			app = macro['app']
			_spawn([app.get('executable_path', '')] + list(app.get('argument_list', [])))
		elif t == 'OPEN_WEB_PAGE':
			_spawn(['xdg-open', macro['open_web_page'].get('url', '')])
		elif t == 'AUDIO':
			import audio_actions
			threading.Thread(target=audio_actions.run, args=(macro['audio'].get('action'),), daemon=True).start()
		elif t == 'DEVICE':
			self.device_action('DEVICE', macro['device'].get('action'), True)

	def _system(self, action):
		if action in SYSTEM_KEYS:
			self.combo(SYSTEM_KEYS[action])
		elif action in SYSTEM_CONSUMER:
			out = self._out()
			out.usage(SYSTEM_CONSUMER[action], True, consumer=True)
			out.usage(SYSTEM_CONSUMER[action], False, consumer=True)
		elif action in SYSTEM_COMMANDS:
			_spawn(SYSTEM_COMMANDS[action])
		elif action in ('SCROLL_LEFT', 'SCROLL_RIGHT'):
			self._out().wheel(-1 if action == 'SCROLL_LEFT' else 1, horizontal=True)

	def _mouse(self, mouse, down):
		action = mouse.get('action')
		if action == 'BUTTON':
			code = uinput.BUTTONS.get(mouse.get('hid_usage', 1))
			if code:
				self._out().key(code, down)
		elif action == 'BUTTON_DOUBLE_CLICK' and down:
			code = uinput.BUTTONS.get(mouse.get('hid_usage', 1), uinput.BTN_LEFT)
			for _ in range(2):
				self._out().tap(code)
		elif action in WHEEL and down:
			clicks, horizontal = WHEEL[action]
			self._out().wheel(clicks, horizontal)
		elif ('MOUSE', action) in DEVICE_ACTIONS:
			self.device_action('MOUSE', action, down)

	def combo(self, usages):
		out = self._out()
		for u in usages:
			out.usage(u, True)
		for u in reversed(usages):
			out.usage(u, False)

	def type_text(self, text):
		out = self._out()
		for ch in text:
			found = char_usage(ch)
			if not found:
				continue
			shift, usage = found
			if shift:
				out.usage(SHIFT, True)
			out.usage(usage, True)
			out.usage(usage, False)
			if shift:
				out.usage(SHIFT, False)

	# --- sequences ------------------------------------------------------------------------

	def _sequence_press(self, button, seq):
		if seq.get('use_toggle_actions'):
			running = self.toggles.pop(button, None)
			if running:
				running.set()
			else:
				stop = threading.Event()
				self.toggles[button] = stop
				self._spawn_loop(seq.get('toggle_sequence', {}), seq, stop)
			return
		if seq.get('use_simple_actions', True) and 'simple_sequence' in seq:
			stop = threading.Event()
			if seq.get('use_repeat_actions'):
				self.held[button] = stop
				self._spawn_loop(seq['simple_sequence'], seq, stop)
			else:
				threading.Thread(target=self.play, args=(seq['simple_sequence'], seq, stop), daemon=True).start()
			return
		self.play(seq.get('press_sequence', {}), seq)
		if seq.get('held_sequence', {}).get('components'):
			stop = threading.Event()
			self.held[button] = stop
			self._spawn_loop(seq['held_sequence'], seq, stop)

	def _sequence_release(self, button, seq):
		stop = self.held.pop(button, None)
		if stop:
			stop.set()
		if not seq.get('use_simple_actions', True) and not seq.get('use_toggle_actions'):
			threading.Thread(target=self.play, args=(seq.get('release_sequence', {}), seq), daemon=True).start()

	def _spawn_loop(self, part, seq, stop):
		def loop():
			while not stop.is_set():
				self.play(part, seq, stop)
		threading.Thread(target=loop, daemon=True).start()

	def play(self, part, seq, stop=None):
		"""Run one StateSequence: its components in order."""
		default = seq.get('default_delay', 50) / 1000 if seq.get('use_default_delay') else 0
		for c in part.get('components', []):
			if stop is not None and stop.is_set() and part.get('interruptible', True):
				return
			self._component(c)
			if default and 'delay' not in c:
				time.sleep(default)

	def _component(self, c):
		out = self._out()
		if 'delay' in c:
			time.sleep(c['delay'].get('duration_ms', 0) / 1000)
		elif 'keyboard' in c:
			out.usage(c['keyboard'].get('hid_usage', 0), c['keyboard'].get('is_down', True))
		elif 'mouse' in c:
			self._mouse_component(out, c['mouse'])
		else:
			kind = next((k for k in COMPONENT_MACROS if k in c), None)
			if kind:
				macro = {'type': kind.upper(), kind: c[kind]}
				self.press(None, macro)
				self.release(None, macro)

	@staticmethod
	def _mouse_component(out, m):
		if 'button' in m:
			code = uinput.BUTTONS.get(m['button'].get('hid_usage', 1))
			if code:
				out.key(code, m['button'].get('is_down', True))
		elif 'wheel' in m:
			out.wheel(1 if m['wheel'].get('is_positive', True) else -1)


def _spawn(cmd):
	try:
		subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
		                 start_new_session=True)
	except OSError:
		pass   # a missing program: nothing to run


# --- the macro library ---------------------------------------------------------------------

import os  # noqa: E402

import store  # noqa: E402

LIBRARY_FILE = os.path.join(store.CONFIG_DIR, 'macros.json')
ASSIGNMENTS_FILE = os.path.join(store.CONFIG_DIR, 'assignments.json')


def library():
	"""{id: macro} of the user's macros."""
	return store._read_json(LIBRARY_FILE, {})


def save_library(macros):
	store._write_json(LIBRARY_FILE, macros)


def new_id(existing):
	n = 1
	while f'm{n}' in existing:
		n += 1
	return f'm{n}'


def assignments():
	"""{device ident: {button: macro id}}."""
	return store._read_json(ASSIGNMENTS_FILE, {})


def save_assignments(data):
	store._write_json(ASSIGNMENTS_FILE, data)


def recorded_sequence(events, keep_delays=True, mode='once'):
	"""A SEQUENCE macro from recorded (usage, is_down, seconds) key events. mode: 'once',
	'held' (repeats while the button is held) or 'toggle' (starts and stops on presses)."""
	components, last = [], None
	for usage, down, t in events:
		if keep_delays and last is not None and t > last:
			components.append({'delay': {'duration_ms': round((t - last) * 1000)}})
		components.append({'keyboard': {'hid_usage': usage, 'is_down': down}})
		last = t
	return sequence_macro(components, keep_delays, mode)


def sequence_components(macro):
	seq = macro.get('sequence', {})
	return (seq.get('simple_sequence') or seq.get('toggle_sequence') or {}).get('components', [])


def sequence_macro(components, keep_delays=True, mode='once'):
	"""A SEQUENCE macro playing components once, while held ('held') or on/off ('toggle')."""
	part = {'components': components, 'interruptible': True}
	seq = {'use_simple_actions': mode != 'toggle', 'use_toggle_actions': mode == 'toggle',
	       'use_repeat_actions': mode == 'held', 'use_default_delay': not keep_delays, 'default_delay': 50}
	seq['toggle_sequence' if mode == 'toggle' else 'simple_sequence'] = part
	return {'type': 'SEQUENCE', 'sequence': seq}
