"""G HUB's audio assignments for buttons and macros (its ASSIGNMENT_NAME_* list): cycle the
equalizer presets, toggle surround, cycle the output / input device, mic gain and volume up / down,
with G HUB's notices for them (OSD_EQUALIZER_CYCLE, OSD_SURROUND_SOUND_TOGGLE_ON / _OFF,
OSD_AUDIO_OUTPUT, OSD_AUDIO_INPUT). On Linux they go through PipeWire (wpctl), so they work with
any headset. Ours: the 5 % volume / gain step, the notices' wording, and cycling the presets in
the order of G HUB's preset file. config.json "audio_notifications": false turns the notices off.

Sidetone and bass up / down change the headset's own setting (HID++ 0x8300 / 0x8305) on the first
connected headset that has it, in steps of 10 (ours). Advanced equalizer toggle turns Lghub's
equalizer on / off. Switch to this audio device makes the first Logitech headset or mic
PipeWire knows the default output and input (ours: which device, as the action carries none).
Not here: treble up / down (no headset Lghub knows has a treble setting).
"""
import subprocess

import store

STEP = '5%'
SINK, SOURCE = '@DEFAULT_AUDIO_SINK@', '@DEFAULT_AUDIO_SOURCE@'
SHOW_MS = 1500
WPCTL = {'MUTE_MICROPHONE': ['set-mute', SOURCE, 'toggle'],
         'MUTE_SPEAKERS': ['set-mute', SINK, 'toggle'],
         'VOLUME_MUTE': ['set-mute', SINK, 'toggle'],
         'VOLUME_UP': ['set-volume', '-l', '1.0', SINK, STEP + '+'],
         'VOLUME_DOWN': ['set-volume', SINK, STEP + '-'],
         'MICROPHONE_GAIN_INCREASE': ['set-volume', '-l', '1.0', SOURCE, STEP + '+'],
         'MICROPHONE_GAIN_DECREASE': ['set-volume', SOURCE, STEP + '-']}
# action -> (HID++ feature, step, notice title)
HEADSET_STEPS = {'SIDETONE_INCREASE': (0x8300, 10, 'Sidetone'), 'SIDETONE_DECREASE': (0x8300, -10, 'Sidetone'),
                 'BASS_INCREASE': (0x8305, 10, 'Bass'), 'BASS_DECREASE': (0x8305, -10, 'Bass')}
ACTIONS = tuple(WPCTL) + ('EQUALIZER_CYCLE', 'SURROUND_TOGGLE', 'AUDIO_OUTPUT_CYCLE', 'AUDIO_INPUT_CYCLE') \
	+ tuple(HEADSET_STEPS) + ('ADVANCED_EQUALIZER_TOGGLE', 'MAKE_DEFAULT_AUDIO_DEVICE')


def _notify(title, body, icon='audio-headphones'):
	if store.load_config().get('audio_notifications', True):
		import battery_watch
		run.shown = battery_watch.notify(title, body, icon, run.shown, SHOW_MS)


def next_after(items, current):
	"""The item after current (the first one when current isn't there)."""
	if not items:
		return None
	return items[(items.index(current) + 1) % len(items)] if current in items else items[0]


def cycle_equalizer():
	"""The next preset, equalizer on; returns its name."""
	import eq
	settings = eq.load()
	names = list(eq.PRESETS)
	name = next_after(names, settings['preset'] if settings['enabled'] else None)
	settings.update(enabled=True, preset=name, gains=list(eq.PRESETS[name]))
	eq.save(settings)
	return name


def toggle_surround():
	import surround
	settings = surround.load()
	settings['enabled'] = not settings['enabled']
	surround.save(settings)
	return settings['enabled']


def toggle_equalizer():
	import eq
	settings = eq.load()
	settings['enabled'] = not settings['enabled']
	eq.save(settings)
	return settings['enabled']


def _headsets():
	"""Connected headsets (corded, or behind a receiver), as devices.Device entries."""
	import devices
	for d in devices.discover():
		if d.model.type == 'receiver':
			try:
				yield from (p for p in devices.scan_receiver(d) if p.model.type in ('headset', 'hid_device'))
			except OSError:
				continue
		elif d.model.type in ('headset', 'hid_device'):
			yield d


def step_headset(feature, step):
	"""Moves a headset setting (0-100) by step on the first headset that has it: its new level,
	or None when no headset has it."""
	import devices
	import hidpp
	for d in _headsets():
		try:
			dev = devices.open_hidpp(d)
		except OSError:
			continue
		try:
			if dev.has(feature):
				level = max(0, min(100, dev.call(feature, 0)[0] + step))
				dev.call(feature, 1, bytes([level]))
				return level
		except hidpp.HidppError:
			continue
		finally:
			dev.close()
	return None


def make_default():
	"""The first Logitech headset or mic becomes the default output and input: its description."""
	import eq
	import pw
	chosen = None
	for nodes in (eq.sinks(), pw.sources()):
		node = next((n for n in nodes if 'logitech' in f"{n['name']} {n['description']}".lower()
		             or pw.is_blue_voice_headset(n) or pw.is_bv2_mic(n)), None)
		if node:
			subprocess.run(['wpctl', 'set-default', str(node['id'])], capture_output=True)
			chosen = chosen or node['description']
	return chosen


def default_name(which):
	"""node.name of the default sink ('SINK') or source ('SOURCE')."""
	try:
		out = subprocess.run(['wpctl', 'inspect', f'@DEFAULT_AUDIO_{which}@'], capture_output=True, text=True,
		                     timeout=5).stdout
	except (OSError, subprocess.TimeoutExpired):
		return None
	for line in out.splitlines():
		line = line.strip().lstrip('* ')
		if line.startswith('node.name = '):
			return line.split('=', 1)[1].strip().strip('"')
	return None


def cycle_device(nodes, current):
	"""Makes the node after current the default; returns it, or None."""
	node = next_after([n['name'] for n in nodes], current)
	if node is None:
		return None
	found = next(n for n in nodes if n['name'] == node)
	subprocess.run(['wpctl', 'set-default', str(found['id'])], capture_output=True)
	return found


def _cycle_output():
	import eq
	node = cycle_device(eq.sinks(), default_name('SINK'))
	if node:
		_notify('Audio output', node['description'])


def _cycle_input():
	import pw
	node = cycle_device(pw.sources(), default_name('SOURCE'))
	if node:
		_notify('Audio input', node['description'], 'audio-input-microphone')


def _step(action):
	feature, step, title = HEADSET_STEPS[action]
	level = step_headset(feature, step)
	if level is not None:
		_notify(title, f'{level} %')


def _make_default():
	name = make_default()
	if name:
		_notify('Audio device', name)


HANDLERS = {'EQUALIZER_CYCLE': lambda: _notify('Equalizer', cycle_equalizer()),
            'SURROUND_TOGGLE': lambda: _notify('Surround sound', 'On' if toggle_surround() else 'Off'),
            'AUDIO_OUTPUT_CYCLE': _cycle_output, 'AUDIO_INPUT_CYCLE': _cycle_input,
            'ADVANCED_EQUALIZER_TOGGLE': lambda: _notify('Equalizer', 'On' if toggle_equalizer() else 'Off'),
            'MAKE_DEFAULT_AUDIO_DEVICE': _make_default}


def run(action):
	"""Runs one of ACTIONS; False if it isn't one."""
	if action in WPCTL:
		subprocess.run(['wpctl'] + WPCTL[action], capture_output=True)
	elif action in HEADSET_STEPS:
		_step(action)
	elif action in HANDLERS:
		HANDLERS[action]()
	else:
		return False
	return True


run.shown = 0           # the last notice, replaced by the next one
