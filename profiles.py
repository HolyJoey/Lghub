"""Per-game profiles: switch settings while a game runs, the way G HUB ties profiles to
applications. A game is described with G HUB's Application fields (name, application_path, and
game.steam.id for Steam games); its profile is a snapshot of Lghub's own settings (Blue VO!CE and
Blue VO!CE 2, equalizer, surround).

How a running game is recognised is ours: its executable's name among the running processes
(Proton games show up as "Game.exe"), or "AppId=<id>" on the command line of the process Steam
starts every game with. Changes made while a game runs stay in its profile (as G HUB edits the
active profile); when the game ends, the settings from before it started come back.
"""
import os
import re
import uuid

import eq
import store
import surround

FILE = os.path.join(store.CONFIG_DIR, 'game_profiles.json')
VOICE_KEYS = ('enabled', 'preset', 'params', 'bv2_preset', 'bv2_effects_preset', 'bv2_params')
CHECK_EVERY = 5.0


def load():
	data = store._read_json(FILE, {})
	data.setdefault('profiles', [])
	return data


def save(data):
	store._write_json(FILE, data)


def new_profile(name, executable='', steam_id=''):
	app = {'name': name, 'application_path': executable.strip()}
	if steam_id.strip():
		app['game'] = {'steam': {'id': steam_id.strip()}}
	return {'id': str(uuid.uuid4()), 'application': app, 'settings': snapshot()}


def snapshot():
	"""Lghub's settings as they are now."""
	cfg = store.load_config()
	return {'voice': {k: cfg[k] for k in VOICE_KEYS if k in cfg},
	        'equalizer': eq.load(), 'surround': surround.load()}


def restore(settings):
	"""Put a snapshot back; the engine picks the files up on its next round."""
	if settings.get('voice'):
		cfg = store.load_config()
		cfg.update(settings['voice'])
		store.save_config(cfg)
	if settings.get('equalizer'):
		eq.save(settings['equalizer'])
	if settings.get('surround'):
		surround.save(settings['surround'])


def _processes():
	"""(executable names, command lines) of the running processes, lower case."""
	names, lines = set(), []
	for pid in os.listdir('/proc'):
		if not pid.isdigit():
			continue
		try:
			with open(f'/proc/{pid}/cmdline', 'rb') as f:
				args = f.read().split(b'\0')
		except OSError:
			continue
		line = b' '.join(args).decode(errors='replace').lower()
		lines.append(line)
		for arg in args[:2]:
			base = arg.decode(errors='replace').replace('\\', '/').rsplit('/', 1)[-1].lower()
			if base:
				names.add(base)
	return names, lines


def running(profiles, processes=None):
	"""The first profile whose game is running, or None."""
	names, lines = processes or _processes()
	for p in profiles:
		app = p.get('application', {})
		exe = app.get('application_path', '').replace('\\', '/').rsplit('/', 1)[-1].lower()
		steam = app.get('game', {}).get('steam', {}).get('id', '')
		if exe and exe in names:
			return p
		if steam and any(re.search(rf'(?:appid|steamgameid)=\s*{re.escape(steam)}(?!\d)', line) for line in lines):
			return p
	return None


def _notify(title, body):
	"""G HUB's profile-activated notification (desktop notifications on, battery_watch's sender)."""
	import store
	if store.load_config().get('profile_notifications', True):
		import battery_watch
		battery_watch.notify(title, body)


class Switcher:
	"""Used by the engine: applies a game's profile while it runs."""

	def __init__(self):
		self.last = 0.0

	def due(self, now):
		return now - self.last >= CHECK_EVERY

	def check(self, now):
		self.last = now
		data = load()
		if not data['profiles'] and not data.get('active'):
			return None
		game = running(data['profiles'])
		active = data.get('active')
		if game and game['id'] != active:
			if not active:
				data['desktop'] = snapshot()
			restore(game['settings'])
			data['active'] = game['id']
			save(data)
			name = game['application'].get('name')
			print(f"engine: {name} started: its profile is on", flush=True)
			_notify(f'{name} profile on', 'Its settings are on while it runs.')
		elif not game and active:
			for p in data['profiles']:      # changes made while it ran belong to its profile, as in G HUB
				if p['id'] == active:
					p['settings'] = snapshot()
			restore(data.pop('desktop', {}))
			data.pop('active', None)
			save(data)
			print('engine: game closed: settings are back', flush=True)
			_notify('Desktop profile on', 'The game closed; your usual settings are back.')
		return data.get('active')
