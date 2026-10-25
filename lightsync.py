"""LIGHTSYNC: keyboard lighting that follows what's playing or what's on screen, like G HUB's
Audio Visualizer and Screen Sampler effects. The background service streams the colours to the
keyboard without saving them in it (per-key lighting, 0x8081 / 0x8080).

- Audio visualizer: the sound going to the default output (PipeWire's monitor of it), on G HUB's
  own per-key layout (audio-visualizer-kb-per-key.json: columns of keys, each with a frequency
  range, lit from the bottom); ours (bands across the keyboard) when that file isn't there.
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

import hidpp
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


def _hz(name):
	"""G HUB's Frequency.Value name (LOW_60HZ, MID_1500HZ, ...) as a number."""
	digits = ''.join(c for c in (name or '') if c.isdigit())
	return int(digits) if digits else 0


def ghub_columns(data):
	"""[(low Hz, high Hz, [key or None, bottom to top])] from G HUB's per-key audio visualizer file
	(audio-visualizer-kb-per-key.json: each entry a frequency range and its keys, gaps included)."""
	info = data.get('audioVisualizerInfo', data)
	out = []
	for entry in info.get('frequencyLayout', []):
		r = entry.get('range', {})
		keys = [f"{s['perKeyType']}:{s['slotCode']}" if s.get('lightingType') == 'PER_KEY' and 'slotCode' in s else None
		        for s in entry.get('slots', [])]
		out.append((_hz(r.get('start')), _hz(r.get('end')), keys))
	return out


def _key_color(n, keys, lit, level, color, back, mode, high, clip=None):
	if n >= lit:
		return list(back)
	if clip and n >= clip[0] * len(keys):         # G HUB's clip zone: the keys above the threshold
		return list(clip[1])
	if mode == 'reactive' and high:
		return [round(a + (b - a) * level) for a, b in zip(color, high)]
	if mode == 'gradient' and high:
		f = n / max(1, len(keys) - 1)
		return [round(a + (b - a) * f) for a, b in zip(color, high)]
	return list(color)


def column_frame(columns, level_of, color, present, background=None, mode='fixed', high=None, clip=None):
	"""As G HUB's visualizer: each column lights its keys from the bottom up to its range's level;
	the rest show the background colour (8 % of the colour when none is set: ours). Colour modes
	(G HUB's): fixed; reactive, from colour to `high` with the level; gradient, from colour at the
	bottom to `high` at the top."""
	back = background or [round(c * 0.08) for c in color]
	out = {}
	for low, top, keys in columns:
		level = level_of(low, top)
		lit = round(level * len(keys))
		for n, key in enumerate(keys):
			if key and key in present:
				out[key] = _key_color(n, keys, lit, level, color, back, mode, high, clip)
	return out


def shape_levels(levels, freqs, options, state):
	"""G HUB's audio options on raw 0-1 levels (their meaning is ours): noise thresholds (bass below
	310 Hz, mid / high above; 0-100 %) cut quiet bands, boost (0-100 %) raises, the max amplitude
	(adaptive: the recent peak; or custom 0-100 %) is full scale, smooth animation lets bars fall
	slowly. state keeps the peak and the last levels between frames."""
	bass_cut = options.get('bass_noise', 0) / 100
	mid_cut = options.get('mid_high_noise', 0) / 100
	out = []
	for level, f in zip(levels, freqs):
		cut = bass_cut if f < 310 else mid_cut
		out.append(0.0 if level <= cut else (level - cut) / (1 - cut))
	if options.get('adaptive', True):
		state['peak'] = max(max(out, default=0), state.get('peak', 0.3) * 0.995, 0.05)
		top = state['peak']
	else:
		top = max(0.05, options.get('max_amplitude', 100) / 100)
	boost = 1 + options.get('boost', 0) / 100
	out = [min(1.0, level / top * boost) for level in out]
	if options.get('smooth', False):
		last = state.get('last') or out
		out = [max(new, old * 0.85) for new, old in zip(out, last)]
	state['last'] = out
	return out


def parse_ppm(data):
	"""(width, height, pixel bytes) of a binary PPM (P6, 8 bits), as grim writes it."""
	parts = data.split(maxsplit=4)
	if len(parts) < 5 or parts[0] != b'P6' or parts[3] != b'255':
		raise ValueError('not an 8-bit P6 picture')
	return int(parts[1]), int(parts[2]), parts[4]


def region_colors(width, height, pixels, step=SAMPLE_STEP, regions=None):
	"""{region: [r, g, b]}: the average of every step-th pixel in each region."""
	out = {}
	stride = width * 3
	for name, (left, top, right, bottom) in (regions or REGIONS).items():
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
	row = 'BOTTOM'
	if fy < 1 / 3:
		row = 'TOP'
	elif fy < 2 / 3:
		row = 'MID'
	if fx < 1 / 3:
		return f'{row}_LEFT'
	if fx >= 2 / 3:
		return f'{row}_RIGHT'
	return 'BOTTOM_CENTER'


def ghub_sampler(data):
	"""(regions, {key: region}) from G HUB's screen_sampler-kb.json: its regions are insets from
	each edge of the screen, and each key names the region it takes."""
	info = data.get('screen_sampler_info', {})
	regions = {}
	for rid, r in info.get('region_map', {}).items():
		regions[rid] = (r.get('left', 0), r.get('top', 0), 1 - r.get('right', 0), 1 - r.get('bottom', 0))
	keys = {}
	for group, slot in info.get('lighting_slots', {}).get('info_map', {}).items():
		for kid, c in slot.get('perKeyMap', {}).get('colorCodeMap', {}).items():
			if c.get('tag') in regions:
				keys[f'{group}:{kid}'] = c['tag']
	return regions, keys


def sampler_regions(per_key):
	"""({region id: (G HUB's name, (left, top, right, bottom))}, {key or zone: region id}) from
	G HUB's sampler file for keyboards (keys) or zonal devices (G HUB's zone names); ({}, {}) if it
	isn't downloaded. Blocks the first time."""
	import json
	import softlight
	path = softlight.fetch(softlight.EFFECTS_DIR + ('screen_sampler-kb.json' if per_key else 'screen_sampler.json'))
	try:
		with open(path) as f:
			data = json.load(f)
	except (OSError, TypeError, ValueError):
		return {}, {}
	regions, keys = ghub_sampler(data)
	if not per_key:
		keys = ghub_zones(path)
	names = {rid: r.get('name', rid) for rid, r in data.get('screen_sampler_info', {}).get('region_map', {}).items()}
	return {rid: (names.get(rid, rid), rect) for rid, rect in regions.items()}, keys


BACKGROUND = 'BACKGROUND_COLOR'   # G HUB's tag for keys without a region; Lghub turns them off (ours)


def edit_sampler(regions, keys, settings):
	"""G HUB's regions and key (or zone) map with the region editor's changes: settings['regions']
	holds every region kept (G HUB's and added ones, id -> rect), settings['assign'] the keys (or
	zones) moved to another region. As in G HUB, keys of a deleted region take BACKGROUND_COLOR."""
	saved = settings.get('regions')
	if saved:
		regions = {rid: tuple(r) for rid, r in saved.items()}
	keys = {**keys, **settings.get('assign', {})}
	return regions, {k: r if r in regions else BACKGROUND for k, r in keys.items()}


def ghub_zones(path):
	"""{G HUB zone name: region} from its zonal screen sampler file."""
	import json
	with open(path) as f:
		info = json.load(f).get('screen_sampler_info', {})
	return {name: slot.get('zone_color', {}).get('tag')
	        for name, slot in info.get('lighting_slots', {}).get('info_map', {}).items()
	        if slot.get('zone_color', {}).get('tag')}


def sampler_frame(layout, colors):
	width, height, keys = layout
	return {f'{group}:{kid}': colors[key_region(x + w / 2, y + h / 2, width, height)]
	        for group, kid, x, y, w, h in keys if group == 'PERKEY_KEYBOARD'}


class PerKeyTarget:
	"""Where an effect's colours go on a per-key keyboard: every key, not saved in it."""

	def __init__(self, dev, layout, light_map=None):
		self.dev, self.layout, self.light_map = dev, layout, light_map
		self.keys = [f'{g}:{k}' for g, k, *_r in layout[2]]
		self.zonal = False

	def send(self, colors):
		perkey.apply(self.dev, colors, persist=False, light_map=self.light_map)


# G HUB's zone names (lighting_support Zone.Type) for HID++ 0x8070 / 0x8071 zone locations; which
# location is which name is ours
ZONE_NAMES = {0: 'ZONE_PRIMARY', 1: 'ZONE_PRIMARY', 2: 'ZONE_BRANDING', 3: 'ZONE_ONE', 4: 'ZONE_TWO',
              6: 'ZONE_ONE', 7: 'ZONE_TWO', 8: 'ZONE_THREE', 9: 'ZONE_FOUR', 10: 'ZONE_FIVE'}


class ZoneTarget:
	"""Where an effect's colours go on a device with lighting zones (mice, speakers, headsets):
	each zone's fixed effect, not saved in it (0x8070 / 0x8071)."""

	def __init__(self, dev):
		import features
		self.dev = dev
		zones = features.zones(dev) if dev.has(features.COLOR_LED_EFFECTS) else features.zones_v2(dev)
		self.fixed = {}
		for z in zones:
			index = next((i for i, eid in z.effects if eid == features.FIXED), None)
			if index is not None:
				self.fixed[f'ZONE:{z.index}'] = (z.index, index, z.feature, ZONE_NAMES.get(z.location, 'ZONE_PRIMARY'))
		self.keys = list(self.fixed)
		self.zonal = True

	def send(self, colors):
		import features
		for key, c in colors.items():
			zone, index, feature, _name = self.fixed[key]
			params = features.effect_params(features.FIXED, tuple(c))
			features.set_effect(self.dev, zone, index, params, persist=False, feature=feature)


def restore_zones(dev):
	"""After an effect on zones: an onboard-memory mouse gets its profile's lighting back by
	selecting its current profile again (ours); other devices keep the last colour until their
	lighting is set again."""
	import mouse
	try:
		if dev.has(mouse.ONBOARD):
			current = dev.call(mouse.ONBOARD, 4)[1]
			dev.call(mouse.ONBOARD, 3, bytes([0, current]))
	except (OSError, hidpp.HidppError):
		pass


def make_target(dev, model):
	layout = perkey.load_layout(model)
	if layout and (dev.has(perkey.PERKEY) or dev.has(perkey.PERKEY_V1)):
		return PerKeyTarget(dev, layout, perkey.load_light_map(model))
	try:
		import features
		if dev.has(features.COLOR_LED_EFFECTS) or dev.has(features.RGB_EFFECTS):
			target = ZoneTarget(dev)
			return target if target.keys else None
	except (OSError, hidpp.HidppError):
		pass
	return None


class Visualizer:
	"""Streams the audio visualizer to one device (an open hidpp.Device) until stopped."""

	def __init__(self, dev, model, color, options=None):
		self.dev, self.model, self.color = dev, model, color
		self.options = options or {}                 # G HUB's visualizer settings (lightsync.json)
		self.target = make_target(dev, model)
		self.layout = self.target.layout if isinstance(self.target, PerKeyTarget) else None
		self.stop_event = threading.Event()
		self.thread = None
		self.proc = None

	def start(self):
		if not self.target:
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

	def _columns(self):
		"""G HUB's visualizer columns for this keyboard, or None to use ours."""
		import json
		import softlight
		if not self.layout:
			return None
		path = softlight.fetch(softlight.EFFECTS_DIR + 'audio-visualizer-kb-per-key.json')
		try:
			with open(path) as f:
				columns = ghub_columns(json.load(f))
		except (OSError, TypeError, ValueError):
			return None
		present = set(self.target.keys)
		return columns if any(k in present for _l, _h, keys in columns for k in keys) else None

	def _run(self):
		columns = self._columns()
		ranges = sorted({(low, high) for low, high, _k in columns}) if columns else []
		freqs = [math.sqrt(max(1, low) * max(1, high)) for low, high in ranges] if columns else band_freqs()
		present = set(self.target.keys)
		state = {}
		background = self.options.get('background')
		mode, high = self.options.get('mode', 'fixed'), self.options.get('color_high')
		clip = ((self.options.get('clip_threshold', 80) / 100, self.options.get('clip_color', [255, 0, 0]))
		        if self.options.get('clip') else None)
		last = 0.0
		while not self.stop_event.is_set():
			data = self.proc.stdout.read(FRAME * 2)
			if not data or len(data) < FRAME * 2:
				return
			if time.monotonic() - last < 1 / FPS:
				continue
			last = time.monotonic()
			samples = [int.from_bytes(data[i:i + 2], 'little', signed=True) / 32768 for i in range(0, len(data), 2)]
			levels = shape_levels(band_levels(samples, freqs), freqs, self.options, state)
			if columns:
				by_range = dict(zip(ranges, levels))
				frame = column_frame(columns, lambda lo, hi, levels=by_range: levels[(lo, hi)], self.color, present,
				                     background, mode, high, clip)
			elif self.layout:
				frame = frame_colors(self.layout, levels, self.color)
			else:                                   # zones: the whole device follows the loudness (ours)
				level = max(levels)
				frame = {k: [round(c * (0.08 + 0.92 * level)) for c in self.color] for k in self.target.keys}
			try:
				self.target.send(frame)
			except (OSError, hidpp.HidppError):
				return


class ScreenSampler(Visualizer):
	"""Streams the screen sampler to one keyboard until stopped."""

	def __init__(self, dev, model, settings):
		super().__init__(dev, model, None)
		self.boost = max(0, min(100, settings.get('color_boost', 0))) * 3 / 100
		self.smoothing = settings.get('smoothing', False)
		self.edits = settings                          # the region editor's regions and key moves

	def start(self):
		if not self.target:
			return False
		self.thread = threading.Thread(target=self._run, daemon=True)
		self.thread.start()
		return True

	def _ghub_regions(self):
		"""G HUB's regions and key (or zone) map, or (None, None) to use ours."""
		import json
		import softlight
		name = 'screen_sampler.json' if self.target.zonal else 'screen_sampler-kb.json'
		path = softlight.fetch(softlight.EFFECTS_DIR + name)
		try:
			with open(path) as f:
				regions, keys = ghub_sampler(json.load(f))
			if self.target.zonal:
				keys = ghub_zones(path)
		except (OSError, TypeError, ValueError):
			return None, None
		regions, keys = edit_sampler(regions, keys, self.edits)
		if self.target.zonal:
			keys = {k: keys[z[3]] for k, z in self.target.fixed.items() if z[3] in keys}
		else:
			present = set(self.target.keys)
			keys = {k: r for k, r in keys.items() if k in present}
		return (regions, keys) if regions and keys else (None, None)

	def _frame(self, colors, keys):
		if keys:
			return {k: colors.get(r, [0, 0, 0]) for k, r in keys.items()}
		if self.layout:
			return sampler_frame(self.layout, colors)
		return {k: colors['BOTTOM_CENTER'] for k in self.target.keys}

	def _run(self):
		shown = None
		regions, keys = self._ghub_regions()
		grab = self._grabber()
		try:
			while grab and not self.stop_event.wait(1 / SCREEN_FPS):
				try:
					colors = region_colors(*grab(), regions=regions)
				except (OSError, subprocess.SubprocessError, ValueError) as e:
					print(f'lightsync: screen sampler stopped: {e}', flush=True)
					return
				shown = self._show(colors, shown, keys)
				if shown is False:
					return
		finally:
			if self.screen:
				self.screen.close()

	def _grabber(self):
		"""grab() -> (width, height, RGB bytes): grim on wlroots compositors (Hyprland, Sway), else
		the screen-sharing portal (GNOME, KDE; asks once); None when neither works."""
		self.screen = None

		def grim():
			shot = subprocess.run(['grim', '-t', 'ppm', '-'], capture_output=True, timeout=5, check=True).stdout
			return parse_ppm(shot)

		try:
			grim()
			return grim
		except (OSError, subprocess.SubprocessError, ValueError):
			pass
		try:
			import screencast
			self.screen = screencast.Screen()
			return self.screen.grab
		except (OSError, ValueError, ImportError) as e:
			print(f'lightsync: screen sampler needs grim or the screen-sharing portal: {e}', flush=True)
			return None

	def _show(self, colors, shown, keys):
		"""Sends one frame if it changed; the colours shown, or False when the device is gone."""
		colors = {k: boost(c, self.boost) for k, c in colors.items()}
		if self.smoothing and shown:
			colors = {k: [round(o + (n - o) * 0.3) for o, n in zip(shown[k], c)] for k, c in colors.items()}
		if colors == shown:
			return shown
		try:
			self.target.send(self._frame(colors, keys))
		except (OSError, hidpp.HidppError):
			return False
		return colors


class Animated(Visualizer):
	"""Streams one of softlight's effects (G HUB's keyframe effects, Starlight, Color cycle) or a
	signature effect (signature.py: Smooth Wave, Smooth Star)."""

	def __init__(self, dev, model, settings, port=None):
		super().__init__(dev, model, None)
		self.settings = settings
		self.port = port
		self.keys = None

	def make(self):
		import json
		import softlight
		s = self.settings
		keys = self.target.keys if self.target.zonal else softlight.layout_keys(self.layout)
		if s['effect'] == 'starlight':
			return softlight.Starlight(keys, s.get('star', (255, 255, 255)), s.get('sky', (0, 0, 40)),
			                           s.get('count', 50), s.get('speed', 2000))
		if s['effect'] in SIGNATURE:
			return self._signature(s)
		if s['effect'] == 'echo':
			return softlight.EchoPress(keys, s.get('echo', (255, 255, 255)), s.get('rest', (0, 0, 0)),
			                           s.get('speed', 1000))
		if s['effect'] == 'cycle':
			return softlight.ColorCycle(keys, s.get('colors') or softlight.CYCLE_COLORS, s.get('speed', 5000))
		if s['effect'] == 'device':                  # the model's own effect (lighting_effects.json)
			effect = dict(softlight.device_effects(self.model)).get(s.get('file'))
			if not effect:
				return None
			frames, speed, direction = softlight.parse_keyframes(effect)
		else:
			if s.get('custom'):
				path = os.path.join(softlight.CUSTOM_DIR, os.path.basename(s['custom']))
			else:
				path = softlight.fetch(softlight.EFFECTS_DIR + s.get('file', ''))
			with open(path) as f:
				frames, speed, direction = softlight.parse_keyframes(json.load(f))
		present = set(keys)
		frames = [(n, c, {k: v for k, v in colors.items() if k in present}) for n, c, colors in frames]
		return softlight.Keyframes(frames, speed, direction) if frames else None

	def _signature(self, s):
		"""A signature effect (signature.py) on the per-key layout, with its two colours; None on
		zonal devices (their roots aren't ported yet)."""
		if self.target.zonal:
			return None
		import signature
		leds, logo, indicator = signature.layout_leds(self.layout)
		d1, d2 = SIGNATURE[s['effect']]
		c1, c2 = tuple(s.get('color', d1)) + (255,), tuple(s.get('color2', d2)) + (255,)
		build = signature.EFFECTS[s['effect']]
		return signature.Player(lambda: build(leds, logo, indicator, c1, c2))

	def start(self):
		if not self.target:
			return False
		self.thread = threading.Thread(target=self._run, daemon=True)
		self.thread.start()
		return True

	def stop(self):
		super().stop()
		if self.keys:
			self.keys.stop()

	def _follow_presses(self, effect):
		"""Echo press: key presses (keyboards) or clicks (mice, every zone echoes: ours) reach the
		effect; False if they can't be read."""
		import keypress
		if self.target.zonal:
			def echo_all(_button):
				for k in self.target.keys:
					effect.press(k)

			self.keys = keypress.Keys(keypress.key_nodes(self.port or '', keypress.BUTTON_PAGE), echo_all)
		else:
			self.keys = keypress.Keys(keypress.key_nodes(self.port or ''),
			                          lambda usage: effect.press(f'PERKEY_KEYBOARD:{usage}'))
		try:
			self.keys.start()
		except OSError as e:
			print(f'lightsync: {e}', flush=True)
			return False
		return True

	def _run(self):
		try:
			effect = self.make()
		except (OSError, TypeError, ValueError, KeyError):
			effect = None
		if effect is None:
			print('lightsync: effect not available', flush=True)
			return
		if hasattr(effect, 'press') and not self._follow_presses(effect):
			return
		start = time.monotonic()
		shown = None
		while not self.stop_event.wait(1 / FPS):
			colors = effect.frame(time.monotonic() - start)
			changed = {k: c for k, c in colors.items() if not shown or shown.get(k) != c}
			shown = colors
			if not changed:
				continue
			try:
				self.target.send(changed)
			except (OSError, hidpp.HidppError):
				return


# signature effects and their default colours (ours)
SIGNATURE = {'smooth_wave': ((0, 127, 255), (255, 255, 255)), 'smooth_star': ((0, 0, 0), (0, 184, 252)),
             'pulsar_point': ((0, 127, 255), (0, 127, 255)), 'remind_me_of': ((255, 64, 0), (0, 0, 0)),
             'g_3_series': ((255, 0, 80), (0, 90, 255)), 'neon': ((255, 0, 200), (0, 0, 0)),
             'outer_space': ((120, 0, 255), (0, 0, 0))}
ANIMATED = ('keyframe', 'device', 'starlight', 'cycle', 'echo') + tuple(SIGNATURE)


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
		wanted = {m: s for m, s in load().items() if s.get('effect') in ('audio', 'screen') + ANIMATED}
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
			if getattr(visualizer.target, 'zonal', False):
				restore_zones(visualizer.dev)

	def _start(self, dev_id, device, settings):
		try:
			dev = devices_open(device)
		except OSError:
			return
		if settings['effect'] == 'screen':
			visualizer = ScreenSampler(dev, device.model.key, settings)
		elif settings['effect'] in ANIMATED:
			visualizer = Animated(dev, device.model.key, settings, device.port)
		else:
			visualizer = Visualizer(dev, device.model.key, settings.get('color', [0, 140, 255]), settings)
		if visualizer.start():
			self.running[dev_id] = (visualizer, settings)
			print(f'engine: {settings["effect"]} LIGHTSYNC on {device.name}', flush=True)

	def stop(self):
		for v, _settings in self.running.values():
			v.stop()
		self.running.clear()
