"""G HUB's software lighting effects for per-key keyboards: its built-in animated effects
(Verticool, Contrastic, Ocean Wave, Lightning, Red White and Blue), Starlight and Color cycle.

The animated ones are G HUB's own files (LGHUB/data/lighting/effects/*.json in its core depot,
listed in effect_prefabs.json), downloaded at first use and not stored in the repo: a list of
frames, each with a length, an easing curve into it and a colour per key (keys by the same ids
as the per-key page), played in G HUB's directions (cycle, reverse, bounce, random); a frame
lasts length x speed milliseconds (G HUB's keyframe_metadata player).

Starlight (StarlightEffect: star colour, sky colour, star count 5-100, speed 100-10000 ms) and
Color cycle (ColorCycleEffect: colours, speed 1000-10000 ms) use G HUB's settings and ranges; the
default values are ours.
"""
import json
import math
import os
import random

import store

EFFECTS_DIR = 'LGHUB/data/lighting/effects/'
PREFABS = 'LGHUB/data/lighting/effect_prefabs.json'
CACHE = os.path.join(store.IMAGE_DIR, 'lighting')
KEY_GROUPS = ('PERKEY_KEYBOARD', 'PERKEY_GKEY', 'PERKEY_CONSUMER', 'PERKEY_BRANDING', 'PERKEY_INDICATOR')

STAR_COUNT = (5, 100)
STAR_SPEED = (100, 10000)
CYCLE_SPEED = (1000, 10000)
CYCLE_COLORS = ((255, 0, 0), (0, 255, 0), (0, 0, 255))      # ours


# --- G HUB's easing curves (logi.protocol.util.Easing, Qt's QEasingCurve order) ----------------

def _in_out(f_in):
	def f(t):
		return f_in(2 * t) / 2 if t < 0.5 else 1 - f_in(2 - 2 * t) / 2
	return f


def _out(f_in):
	return lambda t: 1 - f_in(1 - t)


def _out_in(f_in):
	out = _out(f_in)

	def f(t):
		return out(2 * t) / 2 if t < 0.5 else 0.5 + f_in(2 * t - 1) / 2
	return f


def _bounce_out(t):
	if t < 1 / 2.75:
		return 7.5625 * t * t
	if t < 2 / 2.75:
		t -= 1.5 / 2.75
		return 7.5625 * t * t + 0.75
	if t < 2.5 / 2.75:
		t -= 2.25 / 2.75
		return 7.5625 * t * t + 0.9375
	t -= 2.625 / 2.75
	return 7.5625 * t * t + 0.984375


_IN = {
	'QUAD': lambda t: t * t,
	'CUBIC': lambda t: t ** 3,
	'QUART': lambda t: t ** 4,
	'QUINT': lambda t: t ** 5,
	'SINE': lambda t: 1 - math.cos(t * math.pi / 2),
	'EXPO': lambda t: 0.0 if t <= 0 else 2 ** (10 * (t - 1)),
	'CIRC': lambda t: 1 - math.sqrt(max(0.0, 1 - t * t)),
	'ELASTIC': lambda t: t if t in (0, 1) else -(2 ** (10 * (t - 1))) * math.sin((t - 1 - 0.075) * 2 * math.pi / 0.3),
	'BACK': lambda t: t * t * (2.70158 * t - 1.70158),
	'BOUNCE': lambda t: 1 - _bounce_out(1 - t),
}


def easing(name):
	"""A 0-1 -> 0-1 curve by G HUB's name (LINEAR, INQUAD, OUTINBACK, ... NONE = jump)."""
	name = (name or 'LINEAR').upper()
	if name == 'NONE':
		return lambda t: 1.0 if t >= 1 else 0.0
	for prefix, wrap in (('OUTIN', _out_in), ('INOUT', _in_out), ('OUT', _out), ('IN', lambda f: f)):
		if name.startswith(prefix) and name[len(prefix):] in _IN:
			return wrap(_IN[name[len(prefix):]])
	return lambda t: t


def _hex(c):
	"""[r, g, b] from "#rrggbb" or the short "#rgb"."""
	c = c.lstrip('#')
	if len(c) == 3:
		c = ''.join(d * 2 for d in c)
	return [int(c[i:i + 2], 16) for i in (0, 2, 4)]


def mix(a, b, f):
	return [round(x + (y - x) * f) for x, y in zip(a, b)]


# --- G HUB's effect files ------------------------------------------------------------------

def keyboard_effects(prefabs):
	"""[(name, file)] of G HUB's keyframe effects for RGB per-key keyboards, from effect_prefabs.json."""
	return [(p['name'], p['infoPath']) for p in prefabs.get('list', [])
	        if p.get('type') == 'KEYFRAME' and 'KEYBOARD_RGB_PER_KEY' in p.get('deviceSupport', [])
	        and p.get('infoPath')]


def fetch(name):
	"""Path of one of G HUB's lighting files (by its name in the core depot), downloaded once;
	None if it can't be had. Blocks."""
	import depots
	path = os.path.join(CACHE, os.path.basename(name))
	if os.path.exists(path):
		return path
	try:
		url = depots.SERVER + depots.CORE_DEPOT
		files = depots.files_cached(url)
		data = depots._get(url, *files[name])
		json.loads(data)
	except (OSError, ValueError, KeyError) as e:
		print(f'lghub: no G HUB lighting file {name}: {e}', flush=True)
		return None
	os.makedirs(CACHE, exist_ok=True)
	with open(path + '.tmp', 'wb') as f:
		f.write(data)
	os.replace(path + '.tmp', path)
	return path


def load_prefabs():
	path = fetch(PREFABS)
	try:
		with open(path) as f:
			return json.load(f)
	except (OSError, TypeError, ValueError):
		return {}


def parse_keyframes(data):
	"""(frames, speed, direction) from a G HUB keyframe file; frames = [(length, curve, colours)]
	in order, colours = {"<group>:<id>": [r, g, b]}."""
	info = data.get('keyframeInfo', data)
	frames = []
	for _n, frame in sorted(info.get('keyframeMap', {}).items(), key=lambda kv: int(kv[0])):
		colors = {}
		for group, slot in frame.get('lightingSlots', {}).get('infoMap', {}).items():
			for kid, c in slot.get('perKeyMap', {}).get('colorCodeMap', {}).items():
				if 'hex' in c:
					colors[f'{group}:{kid}'] = _hex(c['hex'])
		frames.append((max(1, frame.get('length', 1)), frame.get('curveType', 'LINEAR'), colors))
	return frames, info.get('speed', 100), info.get('direction', 'CYCLE')


# --- effects: frame(t) -> {"<group>:<id>": [r, g, b]} -------------------------------------

class Keyframes:
	def __init__(self, frames, speed, direction, rng=None):
		self.frames, self.speed, self.direction = frames, speed, direction
		self.rng = rng or random.Random()
		self.order = list(range(len(frames)))
		self.step = 0
		self.start = 0.0

	def _next_index(self, i):
		n = len(self.frames)
		if self.direction == 'RANDOM':
			return self.rng.randrange(n)
		if self.direction == 'REVERSE_CYCLE':
			return (i - 1) % n
		if self.direction == 'BOUNCE' and n > 1:
			self.step = self.step + 1
			period = 2 * (n - 1)
			k = self.step % period
			return k if k < n else period - k
		return (i + 1) % n

	def frame(self, t):
		"""Colours at t seconds (call with t going up)."""
		if not hasattr(self, 'cur'):
			self.prev = self.cur = 0
			self.start = t
		length, curve, colors = self.frames[self.cur]
		duration = length * self.speed / 1000
		while t - self.start >= duration:
			self.start += duration
			self.prev, self.cur = self.cur, self._next_index(self.cur)
			length, curve, colors = self.frames[self.cur]
			duration = length * self.speed / 1000
		f = easing(curve)(min(1.0, (t - self.start) / duration))
		before = self.frames[self.prev][2]
		return {k: mix(before.get(k, c), c, f) for k, c in colors.items()}


class Starlight:
	"""As G HUB's starlight player: up to star-count stars twinkle at once; each fades from the sky
	colour to the star colour over `speed` ms on its in-curve, then back over `speed` ms on its
	out-curve, and a resting key takes its place. Which key comes next (random) is ours."""

	def __init__(self, keys, star=(255, 255, 255), sky=(0, 0, 40), count=50, speed=2000,
	             in_curve='LINEAR', out_curve='LINEAR', rng=None):
		self.keys, self.star, self.sky = list(keys), list(star), list(sky)
		self.count = max(STAR_COUNT[0], min(STAR_COUNT[1], count))
		self.speed = max(STAR_SPEED[0], min(STAR_SPEED[1], speed)) / 1000
		self.fade_in, self.fade_out = easing(in_curve), easing(out_curve)
		self.rng = rng or random.Random()
		self.stars = {}        # key -> start time

	def frame(self, t):
		self.stars = {k: s for k, s in self.stars.items() if t - s < 2 * self.speed}
		resting = [k for k in self.keys if k not in self.stars]
		while len(self.stars) < self.count and resting:
			k = resting.pop(self.rng.randrange(len(resting)))
			self.stars[k] = t
		out = {k: list(self.sky) for k in self.keys}
		for k, s in self.stars.items():
			phase = (t - s) / self.speed
			if phase < 1:
				out[k] = mix(self.sky, self.star, self.fade_in(phase))
			else:
				out[k] = mix(self.star, self.sky, self.fade_out(phase - 1))
		return out


class ColorCycle:
	"""As G HUB's colour cycle player: from one colour to the next over `speed` ms on its curve,
	then holding it for `delay` ms, through the colours in order."""

	def __init__(self, keys, colors=CYCLE_COLORS, speed=5000, delay=0, curve='LINEAR'):
		self.keys, self.colors = list(keys), [list(c) for c in colors] or [[255, 255, 255]]
		self.speed = max(CYCLE_SPEED[0], min(CYCLE_SPEED[1], speed)) / 1000
		self.delay = max(0, delay) / 1000
		self.curve = easing(curve)

	def frame(self, t):
		n = len(self.colors)
		step = self.speed + self.delay
		i = int(t // step) % n
		f = min(1.0, (t % step) / self.speed)
		c = mix(self.colors[i], self.colors[(i + 1) % n], self.curve(f))
		return dict.fromkeys(self.keys, c)


class EchoPress:
	"""G HUB's Echo press (EchoPressEffect: echo colour, rest colour, speed 100-10000 ms, in / out
	curves): a pressed key lights in the echo colour and fades back to the rest colour. The fade's
	shape and the default values are ours."""

	def __init__(self, keys, echo=(255, 255, 255), rest=(0, 0, 0), speed=1000, out_curve='OUTQUAD'):
		self.keys, self.echo, self.rest = list(keys), list(echo), list(rest)
		self.speed = max(STAR_SPEED[0], min(STAR_SPEED[1], speed)) / 1000
		self.curve = easing(out_curve)
		self.pressed = {}       # key -> time
		self.now = 0.0

	def press(self, key):
		self.pressed[key] = self.now

	def frame(self, t):
		self.now = t
		out = {k: list(self.rest) for k in self.keys}
		self.pressed = {k: s for k, s in self.pressed.items() if t - s < self.speed}
		for k, s in self.pressed.items():
			if k in out:
				out[k] = mix(self.echo, self.rest, self.curve((t - s) / self.speed))
		return out


# --- your own animations (G HUB's Freestyle), in G HUB's keyframe format ------------------------

CUSTOM_DIR = os.path.join(store.CONFIG_DIR, 'animations')
DIRECTIONS = ('CYCLE', 'REVERSE_CYCLE', 'BOUNCE', 'RANDOM')
CURVES = ('LINEAR', 'INQUAD', 'OUTQUAD', 'INOUTQUAD', 'INCUBIC', 'OUTCUBIC', 'INOUTCUBIC', 'INSINE', 'OUTSINE',
          'INOUTSINE', 'INEXPO', 'OUTEXPO', 'INCIRC', 'OUTCIRC', 'INBACK', 'OUTBACK', 'INBOUNCE', 'OUTBOUNCE',
          'INELASTIC', 'OUTELASTIC', 'NONE')
CUSTOM_SPEED = 100        # ms per length unit, as G HUB's own animation files use


def to_ghub(frames, direction='CYCLE', speed=CUSTOM_SPEED):
	"""G HUB's keyframe JSON for [(length, curve, {"<group>:<id>": [r, g, b]})]."""
	keyframes = {}
	for n, (length, curve, colors) in enumerate(frames):
		slots = {}
		for key, rgb in colors.items():
			group, _sep, kid = key.partition(':')
			slots.setdefault(group, {'perKeyMap': {'colorCodeMap': {}}})['perKeyMap']['colorCodeMap'][kid] = \
				{'hex': '#%02x%02x%02x' % tuple(rgb)}
		keyframes[str(n)] = {'curveType': curve, 'length': length, 'lightingSlots': {'infoMap': slots}}
	return {'keyframeInfo': {'direction': direction, 'speed': speed, 'keyframeMap': keyframes}}


def save_custom(name, frames, direction='CYCLE'):
	"""Write an animation; returns its file name in CUSTOM_DIR."""
	os.makedirs(CUSTOM_DIR, exist_ok=True)
	safe = ''.join(c if c.isalnum() else '-' for c in name.lower()).strip('-') or 'animation'
	file = f'{safe}.json'
	data = to_ghub(frames, direction)
	data['name'] = name
	store._write_json(os.path.join(CUSTOM_DIR, file), data)
	return file


def custom_effects():
	"""[(name, file)] of the saved animations."""
	out = []
	try:
		files = sorted(os.listdir(CUSTOM_DIR))
	except OSError:
		return out
	for file in files:
		if file.endswith('.json'):
			data = store._read_json(os.path.join(CUSTOM_DIR, file), {})
			out.append((data.get('name') or file[:-5], file))
	return out


def layout_keys(layout):
	_w, _h, keys = layout
	return [f'{g}:{k}' for g, k, *_r in keys if g in KEY_GROUPS]
