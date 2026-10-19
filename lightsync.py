"""LIGHTSYNC audio visualizer: keyboard lighting that follows what's playing, like G HUB's Audio
Visualizer effect. The background service reads the sound going to the default output
(PipeWire's monitor of it), splits it into frequency bands, one per stretch of keyboard columns
left (bass) to right (treble), and streams the colours to the keyboard without saving them in it
(per-key lighting, 0x8081 / 0x8080). How the bands map onto keys is ours.

lightsync.json in the config folder: {model key: {"effect": "audio", "color": [r, g, b]}}.
"""
import math
import os
import subprocess
import threading
import time

import perkey
import store

FILE = os.path.join(store.CONFIG_DIR, 'lightsync.json')
RATE = 16000
FRAME = 512                 # samples per analysis: 32 ms
BANDS = 8
LOW_HZ, HIGH_HZ = 60, 6000
FPS = 25
FLOOR_DB = -60.0


def load():
	return store._read_json(FILE, {})


def save(data):
	store._write_json(FILE, data)


def band_freqs(bands=BANDS):
	"""Band centres, spread evenly on a log scale from LOW_HZ to HIGH_HZ."""
	step = (math.log(HIGH_HZ) - math.log(LOW_HZ)) / (bands - 1)
	return [LOW_HZ * math.exp(i * step) for i in range(bands)]


def band_levels(samples, freqs, rate=RATE):
	"""0-1 level per band (a single DFT bin per band centre, Hann window, dB scaled)."""
	n = len(samples)
	if not n:
		return [0.0] * len(freqs)
	window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
	x = [s * w for s, w in zip(samples, window)]
	levels = []
	for f in freqs:
		w = 2 * math.pi * f / rate
		re = sum(v * math.cos(w * i) for i, v in enumerate(x))
		im = sum(v * math.sin(w * i) for i, v in enumerate(x))
		power = (re * re + im * im) / (n * n)
		db = 10 * math.log10(power + 1e-12)
		levels.append(max(0.0, min(1.0, (db - FLOOR_DB) / -FLOOR_DB)))
	return levels


def frame_colors(layout, levels, color):
	"""{"<group>:<id>": [r, g, b]} for a frame: each key column belongs to a band by its x; keys
	light up from the bottom as high as the band's level."""
	width, height, keys = layout
	out = {}
	for group, kid, x, y, w, h in keys:
		if group != 'PERKEY_KEYBOARD':
			continue
		band = min(len(levels) - 1, int((x + w / 2) / max(1, width) * len(levels)))
		row = 1 - (y + h / 2) / max(1, height)          # 0 at the bottom, 1 at the top
		on = levels[band] >= row
		scale = 1.0 if on else 0.08
		out[f'{group}:{kid}'] = [round(c * scale) for c in color]
	return out


class Visualizer:
	"""Streams the audio visualizer to one keyboard (an open hidpp.Device) until stopped."""

	def __init__(self, dev, model, color):
		self.dev, self.model, self.color = dev, model, color
		self.layout = perkey.load_layout(model)
		self.stop_event = threading.Event()
		self.thread = None
		self.proc = None

	def start(self):
		if not self.layout:
			return False
		self.proc = subprocess.Popen(['pw-record', '--rate', str(RATE), '--channels', '1', '--format', 's16',
		                              '-P', 'stream.capture.sink=true', '-P', 'node.name=lghub-lightsync', '-'],
		                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
		self.thread = threading.Thread(target=self._run, daemon=True)
		self.thread.start()
		return True

	def stop(self):
		self.stop_event.set()
		if self.proc:
			self.proc.terminate()
		if self.thread:
			self.thread.join(2)

	def _run(self):
		freqs = band_freqs()
		last = 0.0
		while not self.stop_event.is_set():
			data = self.proc.stdout.read(FRAME * 2)
			if not data or len(data) < FRAME * 2:
				return
			if time.monotonic() - last < 1 / FPS:
				continue
			last = time.monotonic()
			samples = [int.from_bytes(data[i:i + 2], 'little', signed=True) / 32768 for i in range(0, len(data), 2)]
			try:
				perkey.apply(self.dev, frame_colors(self.layout, band_levels(samples, freqs), self.color),
				             persist=False)
			except OSError:
				return


class Runner:
	"""Used by the engine: one Visualizer per connected keyboard that has the effect on."""
	CHECK_EVERY = 10.0

	def __init__(self):
		self.running = {}         # device id -> (Visualizer, settings)
		self.last = 0.0
		self.mtime = None

	def due(self, now):
		try:
			mtime = os.stat(FILE).st_mtime
		except OSError:
			mtime = None
		changed, self.mtime = mtime != self.mtime, mtime
		return changed or now - self.last >= self.CHECK_EVERY

	def check(self, now):
		import devices
		self.last = now
		wanted = {m: s for m, s in load().items() if s.get('effect') == 'audio'}
		if not wanted and not self.running:
			return
		found = {d.id: d for d in devices.discover() if d.model.key in wanted}
		for dev_id in tuple(self.running):
			v, settings = self.running[dev_id]
			d = found.get(dev_id)
			if not d or wanted.get(d.model.key) != settings:
				self.running.pop(dev_id)[0].stop()
				if d:   # switched off: the saved colours back on
					import restore
					restore.apply_saved(v.dev, d.model.key)
		for dev_id, d in found.items():
			if dev_id in self.running:
				continue
			try:
				v = Visualizer(devices.open_hidpp(d), d.model.key, wanted[d.model.key].get('color', [0, 140, 255]))
			except OSError:
				continue
			if v.start():
				self.running[dev_id] = (v, wanted[d.model.key])
				print(f'engine: audio visualizer on {d.name}', flush=True)

	def stop(self):
		for v, _settings in self.running.values():
			v.stop()
		self.running.clear()
