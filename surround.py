"""Headset surround: G HUB's DTS Headphone:X 2.0 on a virtual 7.1 output.

The engine runs surround-bridge (Logitech's playback effect, loaded natively) when surround is
on and a headset is there, and links it while apps play: the 7.1 output's monitor into the DSP,
the DSP's stereo out into the headset. With the equalizer on, the bridge applies the same EQ
itself: routing through the equalizer's output would keep the headset awake or stall.
"""
import os
import subprocess
import time

import eq
import pw
import store

SURROUND_FILE = os.path.join(store.CONFIG_DIR, 'surround.json')
PARAMS_FILE = os.path.join(store.RUN_DIR, 'surround.params')
SINK = 'lghub_surround'
DSP = 'lghub_surround_dsp'
CHANNELS = ('FL', 'FR', 'FC', 'LFE', 'RL', 'RR', 'SL', 'SR')
CHANNEL_NAMES = {'FL': 'Front left', 'FR': 'Front right', 'FC': 'Centre', 'LFE': 'Subwoofer',
                 'RL': 'Rear left', 'RR': 'Rear right', 'SL': 'Side left', 'SR': 'Side right'}
DEFAULT_GAIN = 1.1          # G HUB's default volume for every channel (its SurroundSound settings)
# G HUB's headset rooms (logi.protocol.audio.DTSSettings.HeadsetRoomPreset: HX2E_ENTERTAINMENT = 11,
# HX2E_GAMING = 12, HX2E_SPORTS = 13); the DLL numbers them from 0 in the same order.
ROOMS = (('gaming', 'Gaming', 1), ('entertainment', 'Entertainment', 0), ('sports', 'Sports', 2))
DEFAULT_ROOM = 'gaming'     # G HUB's default (headsetRoom HX2E_GAMING)
CHECK_EVERY = 60.0          # fallback; the engine asks for a check on hotplug and link changes
IDLE_GRACE = 5.0            # keep the headset linked this long after the last app stops playing

# The DLL's tuning per headset, picked from the headset's name in PipeWire.
TUNINGS = (('g733', 'G733'), ('g735', 'G735'), ('g935', 'G935'), ('g635', 'G635'), ('g432', 'G432'),
           ('g431', 'G431'), ('pro x 2', 'PRO_X2'), ('wireless', 'PRO_X_WIRELESS'), ('', 'PRO_X'))


def default_settings():
	return {'enabled': False, 'make_default': True, 'room': DEFAULT_ROOM, 'gains': dict.fromkeys(CHANNELS, DEFAULT_GAIN)}


def load():
	settings = default_settings()
	saved = store._read_json(SURROUND_FILE, {})
	settings['enabled'] = bool(saved.get('enabled', False))
	settings['make_default'] = bool(saved.get('make_default', True))
	if saved.get('room') in {key for key, _name, _id in ROOMS}:
		settings['room'] = saved['room']
	for c, g in (saved.get('gains') or {}).items():
		if c in CHANNELS and isinstance(g, (int, float)):
			settings['gains'][c] = max(0.0, min(2.0, float(g)))
	return settings


def save(settings):
	store._write_json(SURROUND_FILE, settings)


def tuning(sink):
	text = f"{sink['name']} {sink['description']}".lower().replace('_', ' ')
	return next(name for key, name in TUNINGS if key in text)


def params_text(settings, equalizer=None):
	"""The bridge's settings file; with the equalizer on, its gains go along so surround sound
	gets the same EQ (it can't go through the equalizer's own output, see _link)."""
	room = next(dll_id for key, _name, dll_id in ROOMS if key == settings.get('room', DEFAULT_ROOM))
	lines = ['state 1', f'room {room}'] + [f'gain_{c} {settings["gains"][c]:.3f}' for c in CHANNELS]
	if equalizer and equalizer.get('enabled'):
		lines += ['eq 1'] + [f'eq_{i + 1} {g:.2f}' for i, g in enumerate(equalizer['gains'])]
	return '\n'.join(lines) + '\n'


def available():
	return os.path.exists(store.HX2E_DLL) and os.path.exists(store.SURROUND_BRIDGE)


class Runner:
	"""Used by the engine, like eq.Runner."""

	def __init__(self):
		self.proc = None
		self.headset = None       # node.name of the headset sink it was started for
		self.mtime = None
		self.settings = default_settings()
		self.eq_mtime = None
		self.defaulted = False
		self.last_check = 0.0
		self.last_playing = 0.0
		self.next_check = 0.0      # an earlier check when something is about to change
		self.wake = False          # set by the engine's link watcher: an app started or stopped

	def due(self):
		mtime, eq_mtime = _mtime(SURROUND_FILE), _mtime(eq.EQ_FILE)
		if (mtime, eq_mtime) != (self.mtime, self.eq_mtime):
			self.mtime, self.eq_mtime = mtime, eq_mtime
			self.settings = load()
			self._write_params()
			return True
		if self.wake:
			self.wake = False
			return True
		now = time.monotonic()
		return now - self.last_check >= CHECK_EVERY or (self.next_check and now >= self.next_check)

	def _write_params(self):
		os.makedirs(store.RUN_DIR, exist_ok=True)
		tmp = PARAMS_FILE + '.tmp'
		with open(tmp, 'w') as f:
			f.write(params_text(self.settings, eq.load()))
		os.replace(tmp, PARAMS_FILE)

	def check(self, objs):
		self.last_check = time.monotonic()
		self.next_check = 0.0
		if self.proc and self.proc.poll() is not None:
			self.proc = None
		headset = pw_headset(objs) if self.settings['enabled'] and available() else None
		if not headset:
			self.stop(objs)
			return
		if not self.proc or headset['name'] != self.headset:
			self.stop(objs)
			self._start(headset)
			return
		self._link(objs, headset)
		if self.settings['make_default'] and not self.defaulted and pw.node_id(SINK, objs) is not None:
			subprocess.run(['wpctl', 'set-default', str(pw.node_id(SINK, objs))], capture_output=True)
			self.defaulted = True

	def _start(self, headset):
		self._write_params()
		cmd = [store.SURROUND_BRIDGE, '--dll', store.HX2E_DLL, '--headset', tuning(headset),
		       '--settings', PARAMS_FILE, '--description', f"{headset['description']} (Surround 7.1)"]
		try:
			self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
			                             stderr=subprocess.DEVNULL, start_new_session=True)
		except OSError as e:
			print(f'engine: surround not started: {e}', flush=True)
			return
		self.headset = headset['name']
		self.defaulted = False
		self.next_check = time.monotonic() + 1   # link once its ports exist
		print(f"engine: surround on {headset['name']} ({tuning(headset)})", flush=True)

	def _link(self, objs, headset):
		"""While an app plays into the 7.1 output (and a few seconds after): monitor -> DSP ->
		headset. Otherwise unlinked, so the headset can go idle like it would without us."""
		now = time.monotonic()
		playing = pw.links_into_node(SINK, objs) > 0
		if playing:
			self.last_playing = now
		active = now - self.last_playing < IDLE_GRACE
		if active and not playing:
			self.next_check = self.last_playing + IDLE_GRACE + 0.1   # unlink when the grace ends
		for c in CHANNELS:
			src, dst = f'{SINK}:monitor_{c}', f'{DSP}:in_{c}'
			linked = src in pw.links_into(dst, objs)
			if active and not linked:
				pw.link(src, dst)
			elif linked and not active:
				pw.unlink(src, dst)
		for c in ('FL', 'FR'):
			out, port = f'{DSP}:out_{c}', f"{headset['name']}:playback_{c}"
			linked = out in pw.links_into(port, objs)
			if active and not linked:
				pw.link(out, port)
			elif linked and not active:
				pw.unlink(out, port)

	def stop(self, objs=None):
		if not self.proc:
			return
		if self.defaulted and self.headset:
			back = eq.SINK if pw.node_id(eq.SINK, objs) is not None else self.headset
			nid = pw.node_id(back, objs)
			if nid is not None:
				subprocess.run(['wpctl', 'set-default', str(nid)], capture_output=True)
		self.proc.terminate()
		try:
			self.proc.wait(timeout=5)
		except subprocess.TimeoutExpired:
			self.proc.kill()
		self.proc = None
		self.headset = None
		self.defaulted = False


def _mtime(path):
	try:
		return os.stat(path).st_mtime
	except FileNotFoundError:
		return None


def pw_headset(objs):
	"""The headset sink to put surround in front of (a G Pro X or G733 output)."""
	return next((s for s in eq.sinks(objs) if pw.is_blue_voice_headset(s)), None)
