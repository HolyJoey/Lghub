"""On-disk state shared by the app and the engine.

config.json  what the user chose: on/off, input mic, current parameters, preset name
presets/     presets the user saved
status.json  what the engine is doing right now (runtime dir; written by the engine only)
"""
import json
import os
import re

import presets

APP_NAME = 'lghub-bluevoice'
DATA_DIR = os.path.join(os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')), APP_NAME)
CONFIG_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')), APP_NAME)
RUN_DIR = os.path.join(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/{APP_NAME}-{os.getuid()}'), APP_NAME)

CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
PRESET_DIR = os.path.join(CONFIG_DIR, 'presets')
STATUS_FILE = os.path.join(RUN_DIR, 'status.json')
PARAMS_FILE = os.path.join(RUN_DIR, 'live.params')

# Files fetched from Logitech at install time (see fetch.py).
APO_DLL = os.path.join(DATA_DIR, 'apo', 'logi_audio_dts_studio_capture_apo.dll')
GHUB_PRESETS = os.path.join(DATA_DIR, 'presets', 'pro_x_headset_device_presets.json')
HOST_EXE = os.path.join(DATA_DIR, 'bin', 'bluevoice_host.exe')
BRIDGE = os.path.join(DATA_DIR, 'bin', 'bluevoice-bridge')
WINE_PREFIX = os.path.join(DATA_DIR, 'wine')

DEFAULT_PRESET = 'BLUE_VOICE_PRESET_BROADCASTER_1'
JSON_EXT = '.json'


def _read_json(path, fallback):
	try:
		with open(path) as f:
			return json.load(f)
	except (OSError, json.JSONDecodeError):
		return fallback


def _write_json(path, data):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	tmp = path + '.tmp'
	with open(tmp, 'w') as f:
		json.dump(data, f, indent=2)
	os.replace(tmp, path)


def ghub_presets():
	"""[(key, display name, params)], or [] before the Logitech files are installed."""
	try:
		return presets.load_ghub_presets(GHUB_PRESETS)
	except (OSError, ValueError, KeyError):
		return []


def default_config():
	params = dict(presets.DEFAULTS)
	name = 'Default'
	for key, display, p in ghub_presets():
		if key == DEFAULT_PRESET:
			params, name = p, display
	return {
		'enabled': True,          # off = clean pass-through; the virtual mic stays available
		'input': 'auto',          # node.name of the real microphone, or 'auto'
		'make_default': False,    # make "Blue VO!CE Microphone" the system's default input
		'max_latency_ms': 40,
		'preset': name,           # label only; 'params' is what is applied
		'params': params,
	}


def load_config():
	cfg = default_config()
	saved = _read_json(CONFIG_FILE, {})
	params = {**cfg['params'], **saved.get('params', {})}
	cfg.update(saved)
	cfg['params'] = params
	return cfg


def save_config(cfg):
	_write_json(CONFIG_FILE, cfg)


def safe_name(name):
	cleaned = re.sub(r'[^\w -]', '', name).strip()
	return cleaned or 'preset'


def preset_path(name):
	return os.path.join(PRESET_DIR, safe_name(name) + JSON_EXT)


def list_user_presets():
	os.makedirs(PRESET_DIR, exist_ok=True)
	return sorted(f[:-len(JSON_EXT)] for f in os.listdir(PRESET_DIR) if f.endswith(JSON_EXT))


def load_user_preset(name):
	data = _read_json(preset_path(name), None)
	return {**presets.DEFAULTS, **data['params']} if data and 'params' in data else None


def save_user_preset(name, params):
	_write_json(preset_path(name), {'name': name, 'params': params})


def delete_user_preset(name):
	try:
		os.remove(preset_path(name))
	except FileNotFoundError:
		pass


def read_status():
	return _read_json(STATUS_FILE, {})


def write_status(status):
	_write_json(STATUS_FILE, status)
