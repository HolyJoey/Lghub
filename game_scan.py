"""Finds installed games to add as profiles, like G HUB's game scan, from the Linux launchers:
- Steam: libraryfolders.vdf and each library's appmanifest_<id>.acf; Steam's own tools (Proton,
  runtimes, redistributables) are left out by name (that list is ours).
- Heroic / Legendary (Epic): installed.json, title and executable.
- Heroic (GOG): gog_store/installed.json, titles from its library cache, the executable from the
  game's goggame-<id>.info (its primary play task).
- Lutris: pga.db (installed games) and each game's YAML (its exe).
Steam games are matched by App ID, the others by their executable's name.
"""
import contextlib
import json
import os
import re
import sqlite3

STEAM_ROOTS = ('~/.steam/steam', '~/.local/share/Steam', '~/.var/app/com.valvesoftware.Steam/.local/share/Steam')
TOOLS = re.compile(r'^(Proton|Steam Linux Runtime|Steamworks Common|Steamworks SDK|SteamVR)', re.I)
_PAIR = re.compile(r'"([^"]*)"\s+"([^"]*)"')


def _values(text):
	"""Every "key" "value" pair of a Valve KeyValues file, as a list (nesting flattened)."""
	return _PAIR.findall(text)


def _read(path):
	try:
		with open(path, encoding='utf-8', errors='replace') as f:
			return f.read()
	except OSError:
		return ''


def libraries(roots=STEAM_ROOTS):
	"""The steamapps folders of every Steam library on this computer."""
	found = []
	for root in roots:
		root = os.path.realpath(os.path.expanduser(root))
		apps = os.path.join(root, 'steamapps')
		if not os.path.isdir(apps):
			continue
		paths = [root] + [v for k, v in _values(_read(os.path.join(apps, 'libraryfolders.vdf'))) if k == 'path']
		for p in paths:
			folder = os.path.join(os.path.realpath(p), 'steamapps')
			if os.path.isdir(folder) and folder not in found:
				found.append(folder)
	return found


def steam_games(roots=STEAM_ROOTS):
	"""[(Steam App ID, name)] of the installed games, by name."""
	games = {}
	for folder in libraries(roots):
		try:
			names = os.listdir(folder)
		except OSError:
			continue
		for name in names:
			if not (name.startswith('appmanifest_') and name.endswith('.acf')):
				continue
			info = dict(_values(_read(os.path.join(folder, name))))
			appid, title = info.get('appid'), info.get('name')
			if appid and title and not TOOLS.match(title):
				games[appid] = title
	return sorted(games.items(), key=lambda g: g[1].lower())


LEGENDARY = ('~/.config/heroic/legendaryConfig/legendary/installed.json', '~/.config/legendary/installed.json')
LUTRIS_DB = ('~/.local/share/lutris/pga.db', '~/.var/app/net.lutris.Lutris/data/lutris/pga.db')
LUTRIS_CONFIGS = ('~/.config/lutris/games', '~/.local/share/lutris/games',
                  '~/.var/app/net.lutris.Lutris/config/lutris/games', '~/.var/app/net.lutris.Lutris/data/lutris/games')


def epic_games(paths=LEGENDARY):
	"""[(name, executable)] of the Epic games installed through Heroic or Legendary."""
	games = {}
	for path in paths:
		try:
			with open(os.path.expanduser(path)) as f:
				data = json.load(f)
		except (OSError, ValueError):
			continue
		for app in data.values() if isinstance(data, dict) else []:
			if isinstance(app, dict) and app.get('title') and app.get('executable'):
				games[app['title']] = os.path.basename(app['executable'].replace('\\', '/'))
	return sorted(games.items(), key=lambda g: g[0].lower())


def _yaml_game_exe(text):
	"""The exe under the top-level "game:" of a Lutris game file, or None."""
	in_game = False
	for line in text.splitlines():
		if line and not line[0].isspace():
			in_game = line.rstrip() == 'game:'
		elif in_game and line.strip().startswith('exe:'):
			value = line.split(':', 1)[1].strip().strip('\'"')
			return os.path.basename(value.replace('\\', '/')) or None
	return None


def _lutris_exe(configpath, dirs):
	for d in dirs:
		exe = _yaml_game_exe(_read(os.path.join(os.path.expanduser(d), f'{configpath}.yml')))
		if exe:
			return exe
	return None


HEROIC_GOG = ('~/.config/heroic/gog_store', '~/.var/app/com.heroicgameslauncher.hgl/config/heroic/gog_store')
HEROIC_CACHE = ('~/.config/heroic/store_cache/gog_library.json',
                '~/.var/app/com.heroicgameslauncher.hgl/config/heroic/store_cache/gog_library.json')


def _gog_titles(caches):
	titles = {}
	for path in caches:
		try:
			with open(os.path.expanduser(path)) as f:
				data = json.load(f)
		except (OSError, ValueError):
			continue
		games = data.get('games', data.get('library', [])) if isinstance(data, dict) else data
		for g in games if isinstance(games, list) else []:
			if isinstance(g, dict) and g.get('app_name') and g.get('title'):
				titles[str(g['app_name'])] = g['title']
	return titles


def _gog_exe(install_path, app):
	try:
		with open(os.path.join(install_path, f'goggame-{app}.info')) as f:
			tasks = json.load(f).get('playTasks', [])
	except (OSError, ValueError, AttributeError):
		return None
	task = next((t for t in tasks if t.get('isPrimary')), tasks[0] if tasks else {})
	path = task.get('path', '')
	return os.path.basename(path.replace('\\', '/')) or None


def gog_games(stores=HEROIC_GOG, caches=HEROIC_CACHE):
	"""[(name, executable)] of the GOG games installed through Heroic."""
	titles = _gog_titles(caches)
	games = {}
	for store in stores:
		try:
			with open(os.path.join(os.path.expanduser(store), 'installed.json')) as f:
				entries = json.load(f).get('installed', [])
		except (OSError, ValueError, AttributeError):
			continue
		for e in entries:
			app = str(e.get('appName', ''))
			exe = _gog_exe(e.get('install_path', ''), app) if app else None
			if exe and not e.get('is_dlc'):
				games[titles.get(app, app)] = exe
	return sorted(games.items(), key=lambda g: g[0].lower())


def installed():
	"""[(name, steam id or '', executable or '')] from every launcher, by name."""
	games = [(n, i, '') for i, n in steam_games()]
	games += [(n, '', exe) for n, exe in epic_games() + gog_games() + lutris_games()]
	return sorted(games, key=lambda g: g[0].lower())


def lutris_games(dbs=LUTRIS_DB, dirs=LUTRIS_CONFIGS):
	"""[(name, executable)] of the installed Lutris games that name an executable."""
	games = {}
	for db in dbs:
		path = os.path.expanduser(db)
		if not os.path.exists(path):
			continue
		try:
			with contextlib.closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as conn:
				rows = conn.execute('SELECT name, configpath FROM games WHERE installed = 1').fetchall()
		except sqlite3.Error:
			continue
		for name, configpath in rows:
			exe = _lutris_exe(configpath, dirs) if configpath else None
			if name and exe:
				games[name] = exe
	return sorted(games.items(), key=lambda g: g[0].lower())
