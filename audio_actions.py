"""G HUB's audio assignments for buttons and macros (its ASSIGNMENT_NAME_* list): cycle the
equalizer presets, toggle surround, cycle the output / input device, mic gain and volume up / down,
with G HUB's notices for them (OSD_EQUALIZER_CYCLE, OSD_SURROUND_SOUND_TOGGLE_ON / _OFF,
OSD_AUDIO_OUTPUT, OSD_AUDIO_INPUT). On Linux they go through PipeWire (wpctl), so they work with
any headset. Ours: the 5 % volume / gain step, the notices' wording, and cycling the presets in
the order of G HUB's preset file. config.json "audio_notifications": false turns the notices off.
Not here: sidetone, bass and treble up / down (device settings, per headset).
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
ACTIONS = tuple(WPCTL) + ('EQUALIZER_CYCLE', 'SURROUND_TOGGLE', 'AUDIO_OUTPUT_CYCLE', 'AUDIO_INPUT_CYCLE')


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


def run(action):
	"""Runs one of ACTIONS; False if it isn't one."""
	if action in WPCTL:
		subprocess.run(['wpctl'] + WPCTL[action], capture_output=True)
	elif action == 'EQUALIZER_CYCLE':
		_notify('Equalizer', cycle_equalizer())
	elif action == 'SURROUND_TOGGLE':
		_notify('Surround sound', 'On' if toggle_surround() else 'Off')
	elif action == 'AUDIO_OUTPUT_CYCLE':
		import eq
		node = cycle_device(eq.sinks(), default_name('SINK'))
		if node:
			_notify('Audio output', node['description'])
	elif action == 'AUDIO_INPUT_CYCLE':
		import pw
		node = cycle_device(pw.sources(), default_name('SOURCE'))
		if node:
			_notify('Audio input', node['description'], 'audio-input-microphone')
	else:
		return False
	return True


run.shown = 0           # the last notice, replaced by the next one
