"""LIGHTSYNC: keyboard lighting that follows what's playing or what's on screen, like G HUB's
Audio Visualizer and Screen Sampler effects. The background service streams the colours to the
keyboard without saving them in it (per-key lighting, 0x8081 / 0x8080).

- Audio visualizer: the sound going to the default output (PipeWire's monitor of it), split into
  frequency bands, one per stretch of keyboard columns left (bass) to right (treble). How the
  bands map onto keys is ours.
- Screen sampler: the average colour of screen regions (G HUB's ScreenSamplerEffect: regions by
  G HUB's names, average colour, colour boost 0-3 shown as 0-100 %, smoothing). The rectangles,
  which key takes which region, and what boost and smoothing do to a colour are ours. Screens
  are read with grim (wlroots compositors: Hyprland, Sway, ...).

lightsync.json in the config folder: {model key: {"effect": "audio", "color": [r, g, b]}} or
{model key: {"effect": "screen", "color_boost": 0-100, "smoothing": bool}}.
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
SCREEN_FPS = 10             # about 14 ms of CPU per frame (grim and the averaging)
SAMPLE_STEP = 8             # every 8th pixel of every 8th row

# G HUB's region names; the rectangles (left, top, right, bottom as fractions of the screen) ours
REGIONS = {
	'TOP_LEFT': (0.0, 0.0, 1 / 3, 1 / 3), 'TOP_RIGHT': (2 / 3, 0.0, 1.0, 1 / 3),
	'MID_LEFT': (0.0, 1 / 3, 1 / 3, 2 / 3), 'MID_RIGHT': (2 / 3, 1 / 3, 1.0, 2 / 3),
	'BOTTOM_LEFT': (0.0, 2 / 3, 1 / 3, 1.0), 'BOTTOM_RIGHT': (2 / 3, 2 / 3, 1.0, 1.0),
	'BOTTOM_CENTER': (1 / 3, 2 / 3, 2 / 3, 1.0),
}


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


def parse_ppm(data):
	"""(width, height, pixel bytes) of a binary PPM (P6, 8 bits), as grim writes it."""
	parts = data.split(maxsplit=4)
	if len(parts) < 5 or parts[0] != b'P6' or parts[3] != b'255':
		raise ValueError('not an 8-bit P6 picture')
	return int(parts[1]), int(parts[2]), parts[4]


def region_colors(width, height, pixels, step=SAMPLE_STEP):
	"""{region: [r, g, b]}: the average of every step-th pixel in each region."""
	out = {}
	stride = width * 3
	for name, (left, top, right, bottom) in REGIONS.items():
		x0, x1 = int(left * width), max(int(left * width) + 1, int(right * width))
		y0, y1 = int(top * height), max(int(top * height) + 1, int(bottom * height))
		sums, count = [0, 0, 0], 0
		for y in range(y0, y1, step):
			row = pixels[y * stride + x0 * 3:y * stride + x1 * 3]
			for c in range(3):
				part = row[c::3 * step]
				sums[c] += sum(part)
			count += len(row[0::3 * step])
		out[name] = [round(s / count) if count else 0 for s in sums]
	return out


def boost(color, amount):
	"""Colour boost (G HUB's 0-3): pushes the colour away from its grey, 0 = as it is."""
	grey = sum(color) / 3
	return [max(0, min(255, round(grey + (c - grey) * (1 + amount)))) for c in color]


def key_region(x, y, width, height):
	"""The region a key at (x, y) takes: by its third of the keyboard, sides by height, the middle
	from the bottom centre."""
	fx, fy = x / max(1, width), y / max(1, height)
	row = 'TOP' if fy < 1 / 3 else 'MID' if fy < 2 / 3 else 'BOTTOM'
	if fx < 1 / 3:
		return f'{row}_LEFT'
	if fx >= 2 / 3:
		return f'{row}_RIGHT'
	return 'BOTTOM_CENTER'


def sampler_frame(layout, colors):
	width, height, keys = layout
	return {f'{group}:{kid}': colors[key_region(x + w / 2, y + h / 2, width, height)]
	        for group, kid, x, y, w, h in keys if group == 'PERKEY_KEYBOARD'}


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


class ScreenSampler(Visualizer):
	"""Streams the screen sampler to one keyboard until stopped."""

	def __init__(self, dev, model, settings):
		super().__init__(dev, model, None)
		self.boost = max(0, min(100, settings.get('color_boost', 0))) * 3 / 100
		self.smoothing = settings.get('smoothing', False)

	def start(self):
		if not self.layout:
			return False
		self.thread = threading.Thread(target=self._run, daemon=True)
		self.thread.start()
		return True

	def _run(self):
		shown = None
		while not self.stop_event.wait(1 / SCREEN_FPS):
			try:
				shot = subprocess.run(['grim', '-t', 'ppm', '-'], capture_output=True, timeout=5, check=True).stdout
				colors = region_colors(*parse_ppm(shot))
			except (OSError, subprocess.SubprocessError, ValueError):
				print('lightsync: screen sampler needs grim (wlroots compositors)', flush=True)
				return
			colors = {k: boost(c, self.boost) for k, c in colors.items()}
			if self.smoothing and shown:
				colors = {k: [round(o + (n - o) * 0.3) for o, n in zip(shown[k], c)] for k, c in colors.items()}
			if colors == shown:
				continue
			shown = colors
			try:
				perkey.apply(self.dev, sampler_frame(self.layout, colors), persist=False)
			except OSError:
				return


def devices_open(device):
	import devices
	return devices.open_hidpp(device)


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
		wanted = {m: s for m, s in load().items() if s.get('effect') in ('audio', 'screen')}
		if not wanted and not self.running:
			return
		present = {d.id: d for d in devices.discover()}
		for dev_id in tuple(self.running):
			self._maybe_stop(dev_id, present.get(dev_id), wanted)
		for dev_id, d in present.items():
			if d.model.key in wanted and dev_id not in self.running:
				self._start(dev_id, d, wanted[d.model.key])

	def _maybe_stop(self, dev_id, device, wanted):
		"""Stop a visualizer whose device is gone or whose setting changed; put the saved colours
		back when the device is still there."""
		visualizer, settings = self.running[dev_id]
		if device and wanted.get(device.model.key) == settings:
			return
		self.running.pop(dev_id)
		visualizer.stop()
		if device:
			import restore
			restore.apply_saved(visualizer.dev, device.model.key)

	def _start(self, dev_id, device, settings):
		try:
			dev = devices_open(device)
		except OSError:
			return
		if settings['effect'] == 'screen':
			visualizer = ScreenSampler(dev, device.model.key, settings)
		else:
			visualizer = Visualizer(dev, device.model.key, settings.get('color', [0, 140, 255]))
		if visualizer.start():
			self.running[dev_id] = (visualizer, settings)
			print(f'engine: {settings["effect"]} LIGHTSYNC on {device.name}', flush=True)

	def stop(self):
		for v, _settings in self.running.values():
			v.stop()
		self.running.clear()
