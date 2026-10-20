"""G HUB's sensitivity presets for a mouse (MOUSE_SETTINGS_ADVANCED in its depot's
defaults_override.json): Default Settings, First Person, MMORPG, ... each with five DPI levels
(some off), the default and shift levels (1-based) and the report rate.

Presets that give X and Y their own DPI (G HUB's "XY Split", asymmetric) are left out: an onboard
profile keeps one DPI per level (ours).
"""
import json

NAMES = {'MSA_PREFAB_00_DEFAULT': 'Default Settings', 'MSA_PREFAB_FIRST_PERSON': 'First Person',
         'MSA_PREFAB_THIRD_PERSON': 'Third Person', 'MSA_PREFAB_MMORPG': 'MMORPG', 'MSA_PREFAB_MOBA': 'MOBA',
         'MSA_PREFAB_RTS': 'RTS', 'MSA_PREFAB_SIMULATION': 'Simulation', 'MSA_PREFAB_PRODUCTIVITY': 'Productivity'}


class Preset:
	def __init__(self, name, levels, default, shift, rate):
		self.name, self.levels, self.default, self.shift, self.rate = name, levels, default, shift, rate


def _name(raw):
	if raw in NAMES:
		return NAMES[raw]
	if raw.startswith('MSA_PREFAB_PRO_'):
		return raw.removeprefix('MSA_PREFAB_PRO_')          # a pro player's handle (G HUB spells it its own way)
	return raw.removeprefix('MSA_PREFAB_').replace('_', ' ').title()


def _levels(entries, slots):
	"""DPI per level (0 = off) from G HUB's 1-based entries."""
	levels = [0] * slots
	for key, e in entries.items():
		if key.isdigit() and 1 <= int(key) <= slots and not e.get('disabled'):
			levels[int(key) - 1] = int(e.get('dpi', 0))
	return levels


def _preset(p, slots):
	"""A Preset from one MOUSE_SETTINGS_ADVANCED preset, or None (XY split, or no first level)."""
	settings = p.get('mouseSettings') or {}
	table = settings.get('advancedDpiTable') or {}
	entries = table.get('entries') or {}
	if not entries or any(e.get('asymmetric') for e in entries.values()):
		return None
	levels = _levels(entries, slots)
	if not levels[0]:
		return None
	used = [i for i, v in enumerate(levels) if v]

	def level(index):
		i = int(index or 1) - 1
		return i if i in used else used[0]
	rate = (settings.get('reportRate') or {}).get('value')
	return Preset(_name(p.get('name', '')), levels, level(table.get('defaultIndex')),
	              level(table.get('shiftIndex')), rate)


def parse(data, slots=5):
	"""[Preset] from a defaults_override.json's contents, G HUB's default first."""
	found = (_preset(p, slots) for p in data.get('presets', []) if p.get('attribute') == 'MOUSE_SETTINGS_ADVANCED')
	out = [p for p in found if p]
	out.sort(key=lambda p: p.name != NAMES['MSA_PREFAB_00_DEFAULT'])
	return out


def load(model):
	"""The model's presets from its downloaded defaults_override.json, [] if none."""
	import depots
	if model not in depots.DEPOTS:
		return []
	try:
		with open(depots.defaults_path(model)) as f:
			return parse(json.load(f))
	except (OSError, ValueError, AttributeError, TypeError):
		return []
