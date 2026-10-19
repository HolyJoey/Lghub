"""Finds installed games to add as profiles, like G HUB's game scan: on Linux, the Steam libraries
(libraryfolders.vdf and each library's appmanifest_<id>.acf). Steam's own tools (Proton, the
runtimes, redistributables) are left out by name; that list is ours.
"""
import os
import re

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
