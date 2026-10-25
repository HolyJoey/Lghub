"""G HUB's signature effect engine and its Smooth Star / Smooth Wave effects.

G HUB builds each signature effect as a tree of frame handlers (namespace signature_effect in its
agent) and steps the tree once per frame; every handler colours the LEDs it owns and says whether
it is still running. These are those handlers, from the agent's step functions:

  Sequencer      0x1412210f0  children one after another (or backwards)
  Parallelizer   0x141221060  all children at once, running while any is
  Pause          0x1412210d0  waits a number of frames
  Gradient       0x1412205d0  keyframes of (frames, angle, gradient), swept across an area
  GradientSampler 0x1412208f0 keyframes of gradients, sampled at fixed positions per LED group
  GradientTween  0x141220b40  keyframes of (frames, line, gradient), the band between two moving
                              lines
  ColorBlend     0x141220490  one colour to another through an easing curve

A gradient is G HUB's stop list (position, colour, bias); between two stops the colour follows
cubic-bezier(0, 0, bias, 1 - bias) (FUN_142a43c50). Colours are (r, g, b, a) bytes, blended per
channel and truncated (0x1410f6c20). LEDs are (id, x, y). The effect trees themselves come from
G HUB's per-effect builders: Smooth Star and Smooth Wave (its effect types 14 / 15) are
ported; G HUB's signature versions of both (type 17, and type 16's style 0) build the same trees.
Type 16's other per-key styles are here too (Pulsar Point, G 3 Series, Remind Me Of, Neon,
Outer Space); their zonal versions and type 18 (G Tide) aren't yet.
"""
import math

import softlight

# Qt's QEasingCurve order, which G HUB's easing function (FUN_142a44080) switches on
EASINGS = ['LINEAR'] + [prefix + name for name in ('QUAD', 'CUBIC', 'QUART', 'QUINT', 'SINE', 'EXPO', 'CIRC',
                                                   'ELASTIC', 'BACK', 'BOUNCE')
                        for prefix in ('IN', 'OUT', 'INOUT', 'OUTIN')]


def curve(index):
	return softlight.easing(EASINGS[index] if 0 <= index < len(EASINGS) else 'LINEAR')


def lerp(a, b, t):
	"""G HUB's colour blend: per channel, truncated toward zero."""
	if t <= 0:
		return tuple(a)
	if t >= 1:
		return tuple(b)
	return tuple(int((y - x) * t + x) for x, y in zip(a, b))


def bezier(x2, y2, u, steps=3):
	"""cubic-bezier(0, 0, x2, y2) at u, solved the way G HUB does (Newton from u, clamped)."""
	if u == 0:
		return 0.0
	ax, bx, cx = 1 - 3 * x2, 3 * x2, 0.0
	ay, by = 1 - 3 * y2, 3 * y2
	s = u
	for _ in range(steps):
		slope = 3 * ax * s * s + 2 * bx * s + cx
		if slope == 0:
			break
		s = min(1.0, max(0.0, s - (ax * s ** 3 + bx * s * s + cx * s - u) / slope))
	return ay * s ** 3 + by * s * s


def sample(stops, p):
	"""Colour of a gradient [(position, colour, bias), ...] at p (0-1)."""
	p = min(1.0, max(0.0, p))
	lo = hi = 0
	for i, stop in enumerate(stops):
		hi = i
		if p <= stop[0]:
			break
		lo = i
	span = stops[hi][0] - stops[lo][0]
	u = (p - stops[lo][0]) / span if span > 0 else 0.0
	bias = stops[lo][2]
	return lerp(stops[lo][1], stops[hi][1], bezier(bias, 1 - bias, u))


class Frame:
	"""What one step paints: {led id: colour}, with G HUB's optional brightness."""

	def __init__(self, brightness=None):
		self.colors = {}
		self.brightness = brightness

	def set(self, led, color):
		if self.brightness is not None:
			color = tuple(int(c * self.brightness / 100) for c in color[:3]) + tuple(color[3:])
		self.colors[led] = color

	def blend(self, led, color, alpha):
		"""color over what this frame already has on the LED (FUN_1411e14e0; that it blends like
		this is ours)."""
		self.set(led, lerp(self.colors.get(led, (0, 0, 0, 0)), color, alpha))


def _inside(area, x, y):
	x0, y0, w, h = area
	return x0 <= x <= x0 + w and y0 <= y <= y0 + h


class Pause:
	def __init__(self, frames):
		self.frames, self.count = frames, 0

	def reset(self):
		self.count = 0

	def step(self, _frame):
		if self.count >= self.frames:
			return False
		self.count += 1
		return True


class Sequencer:
	def __init__(self, children, loop=False, reverse=False):
		self.children, self.loop = children, loop
		self.set_reverse(reverse)

	def set_reverse(self, reverse):
		self.reverse = reverse
		self.index = len(self.children) - 1 if reverse else 0
		self._restart()

	def _restart(self):
		if 0 <= self.index < len(self.children) and hasattr(self.children[self.index], 'reset'):
			self.children[self.index].reset()

	def reset(self):
		self.set_reverse(self.reverse)

	def step(self, frame):
		if not 0 <= self.index < len(self.children):
			if not self.loop:
				return False
			self.reset()           # ours: G HUB's wrap (FUN_141220210) not read yet
		if not self.children[self.index].step(frame):
			self.index += -1 if self.reverse else 1
			self._restart()
		return True


class Parallelizer:
	def __init__(self, children):
		self.children = children

	def reset(self):
		for c in self.children:
			if hasattr(c, 'reset'):
				c.reset()

	def step(self, frame):
		running = False
		for c in self.children:
			running |= bool(c.step(frame))
		return running


class Gradient:
	"""keyframes [(frames, angle in radians, stops)]; the colour sweeps along the angle."""

	def __init__(self, leds, area, keyframes, loop=False):
		self.leds, self.area, self.keyframes, self.loop = leds, area, keyframes, loop
		self.reset()

	def reset(self):
		self.index, self.count, self.previous = 0, 0, self.keyframes[0] if self.keyframes else None

	def step(self, frame):
		if self.index >= len(self.keyframes):
			return False
		cur = self.keyframes[self.index]
		t = self.count / cur[0] if cur[0] else 1.0
		angle = (1 - t) * self.previous[1] + t * cur[1]
		s, c = math.sin(angle), math.cos(angle)
		x0, y0, w, h = self.area
		norm = math.sqrt((s * h) ** 2 + (c * w) ** 2) or 1.0
		for led, x, y in self.leds:
			if _inside(self.area, x, y):
				p = ((y - y0) * s + (x - x0) * c) / norm
				frame.set(led, lerp(sample(self.previous[2], p), sample(cur[2], p), t))
		self.count += 1
		if self.count >= cur[0]:
			self.count, self.previous = 0, cur
			self.index += 1
			if self.loop and self.index >= len(self.keyframes):
				self.index = 0
		return True


class GradientSampler:
	"""keyframes [(frames, stops)]; groups [(position, [led ids])] take the colour at position."""

	def __init__(self, groups, keyframes, loop=False):
		self.groups, self.keyframes, self.loop = groups, keyframes, loop
		self.reset()

	def reset(self):
		self.index, self.count, self.previous = 0, 0, self.keyframes[0] if self.keyframes else None

	def step(self, frame):
		if self.index >= len(self.keyframes):
			return False
		cur = self.keyframes[self.index]
		t = self.count / cur[0] if cur[0] else 0.0
		for position, leds in self.groups:
			color = lerp(sample(self.previous[1], position), sample(cur[1], position), t)
			for led in leds:
				frame.set(led, color)
		self.count += 1
		if self.count >= cur[0]:
			self.count, self.previous = 0, cur
			self.index += 1
			if self.loop and self.index >= len(self.keyframes):
				self.index = 0
		return True


class GradientTween:
	"""keyframes [(frames, (x1, y1, x2, y2) in 0-1 area units, stops)]: the gradient runs along the
	line from (x1, y1) to (x2, y2), which moves to the next keyframe's line; LEDs past either end
	get `outside` (or are left alone with clip)."""

	def __init__(self, leds, area, keyframes, loop=False, clip=False, outside=(0, 0, 0, 0)):
		self.leds, self.area, self.keyframes = leds, area, keyframes
		self.loop, self.clip, self.outside = loop, clip, outside
		self.reset()

	def reset(self):
		self.index, self.count = 0, 0

	def _line(self, a, b, t):
		"""The tweened line in LED coordinates: (x1, y1, dx, dy)."""
		x0, y0, w, h = self.area
		x1, y1, x2, y2 = ((1 - t) * p + t * q for p, q in zip(a[1], b[1]))
		return x1 * w + x0, y1 * h + y0, (x2 - x1) * w, (y2 - y1) * h

	def _advance(self, frames):
		"""Next frame; False once the last keyframe pair is done (and not looping)."""
		self.count += 1
		if self.count < frames:
			return True
		self.count = 0
		self.index += 1
		if self.index + 1 < len(self.keyframes):
			return True
		self.index = 0
		return self.loop

	def step(self, frame):
		if self.index + 1 >= len(self.keyframes):
			return False
		a, b = self.keyframes[self.index], self.keyframes[self.index + 1]
		t = self.count / a[0] if a[0] else 1.0
		x1, y1, dx, dy = self._line(a, b, t)
		length2 = dx * dx + dy * dy
		for led, x, y in self.leds:
			if not _inside(self.area, x, y):
				continue
			along = ((x - x1) * dx + (y - y1) * dy) / length2 if length2 else 0.0
			inside = 0.0 < along < 1.0
			if inside:
				frame.set(led, lerp(sample(a[2], along), sample(b[2], along), t))
			elif not self.clip:
				frame.set(led, self.outside)
		return self._advance(a[0])


class Startup:
	"""G HUB's StartupFrameHandler (0x1412215d0): group1 takes colour b; group2 glows from the top
	centre of the area, lerp(a, b, 1 - (d / size)^p1 * t^p2)."""
	ASPECT, WIDE = 0.357, 2.8011

	def __init__(self, group1, group2, a, b, frames, area=(0.0, 0.0, 1.0, 1.0), p1=1.0, p2=1.0, reverse=False):
		self.group1, self.group2, self.a, self.b, self.frames = group1, group2, a, b, frames
		self.area, self.p1, self.p2, self.reverse = area, p1, p2, reverse
		_x0, _y0, w, h = area
		self.size = math.sqrt((w * self.WIDE * 0.5) ** 2 + (h * self.ASPECT) ** 2)
		self.count = 0

	def reset(self):
		self.count = 0

	def step(self, frame):
		if self.count >= self.frames:
			return False
		x0, y0, w, _h = self.area
		for led, x, y in self.group1:
			if _inside(self.area, x, y):
				frame.set(led, self.b)
		t = self.count / self.frames
		if self.reverse:
			t = 1 - t
		for led, x, y in self.group2:
			if _inside(self.area, x, y):
				dx = abs(x - x0 - w * 0.5)
				d = math.sqrt((2 * dx / self.ASPECT) ** 2 + ((y0 - y) * self.ASPECT) ** 2)
				frame.set(led, lerp(self.a, self.b, 1 - (d / self.size) ** self.p1 * t ** self.p2))
		self.count += 1
		return self.count < self.frames


class Starlight:
	"""G HUB's StarlightFrameHandler (0x141221140): up to max_stars twinkles on random LEDs, each
	fading in, holding and fading out (frames), then moving to another LED. blend: the star goes
	over what is already lit (G HUB's mode 1), else it is the colour at that brightness."""

	def __init__(self, leds, color, fade_in, hold, fade_out, max_stars, blend=True, rng=None):
		import random
		self.leds, self.color, self.blend = list(leds), color, blend
		self.fade_in, self.hold, self.fade_out, self.max_stars = fade_in, hold, fade_out, max_stars
		self.cycle = fade_in + hold + fade_out
		self.rng = rng or random.Random()
		self.stars = []           # [led, age]
		self.acc = 0

	def _brightness(self, age):
		if age < self.fade_in:
			return age / self.fade_in
		if age >= self.hold + self.fade_in:
			return 1 - (age - self.hold - self.fade_in) / self.fade_out
		return 1.0

	def step(self, frame):
		self.acc += self.max_stars
		if self.acc >= self.cycle:
			self.acc = 0
			if len(self.stars) < self.max_stars and self.leds:
				self.stars.append([self.leds[0], self.cycle])
		for star in self.stars:
			if star[1] >= self.cycle:
				star[0], star[1] = self.rng.choice(self.leds), 0
			b = max(0.0, min(1.0, self._brightness(star[1])))
			if self.blend:
				frame.blend(star[0], self.color, b)
			else:                 # G HUB: HSV value (b * 0.5 + 0.5) x a constant; plain scaling here (ours)
				frame.set(star[0], tuple(int(c * (b * 0.5 + 0.5)) for c in self.color[:3]) + (255,))
			star[1] += 1
		return True


FPS = 30                        # ours: the rate G HUB steps its software engine at isn't known


# --- Smooth Wave (effect type SMOOTH_WAVE = 15), G HUB's builder 0x14121b700 -----------------
# Tween keyframes (frames, line x1 y1 x2 y2, stops); stop colours are names filled in by
# smooth_wave(): C1 = the effect's first colour, C2H = its second at half value, BLUE = #AFC9D5,
# OFF = G HUB's constant colour (set at runtime; transparent black here, ours).
C1, C2H, BLUE, OFF = 'C1', 'C2H', 'BLUE', 'OFF'
_SW_FADE = ((0, OFF, 0.5), (1.0, OFF, 0.5))
_SW_HEAD = ((0, C1, 0.5), (0.82, C1, 0.54), (1.0, OFF, 0.5))
_SW_A = (
	(39, (1.03, 0.91, 1.0, 1.0), _SW_FADE),
	(27, (0.77, 0.75, 1.0, 1.0), _SW_HEAD),
	(12, (0.59, 0.81, 1.0, 1.0), ((0, C2H, 0.51), (0.81, BLUE, 0.54), (1.0, OFF, 0.5))),
	(50, (0.57, 0.83, 1.0, 1.0), ((0, C2H, 0.77), (0.82, BLUE, 0.65), (1.0, OFF, 0.5))),
	(81, (0.47, 0.9, 1.0, 1.0), ((0, C2H, 0.77), (0.82, BLUE, 0.65), (1.0, OFF, 0.5))),
	(0, (-0.26, 1.03, 1.0, 1.0), _SW_FADE),
)
_SW_TAIL = ((0, C1, 0.77), (0.82, BLUE, 0.65), (1.0, OFF, 0.5))
_SW_MID = ((0, C1, 0.51), (0.81, BLUE, 0.54), (1.0, OFF, 0.5))
_SW_B = (
	(53, (-0.03, 0.86, -0.01, 0.98), _SW_FADE),
	(44, (0.33, 0.45, -0.01, 0.98), _SW_HEAD),
	(23, (0.33, 0.25, -0.01, 0.98), _SW_MID),
	(67, (0.29, 0.06, -0.01, 0.98), _SW_TAIL),
	(0, (0, -0.8, -0.01, 0.98), _SW_FADE),
)
_SW_C = (
	(45, (1.42, 1.41, 0.99, 0.96), _SW_FADE),
	(37, (0.5, 0.43, 0.99, 0.96), _SW_HEAD),
	(15, (0.49, 0.33, 0.99, 0.96), _SW_MID),
	(88, (0.56, 0.14, 0.99, 0.96), _SW_TAIL),
	(0, (1.63, -1.04, 0.99, 0.96), _SW_FADE),
)
_SW_D = (
	(51, (-0.51, 1.23, 0.02, 0.92), _SW_FADE),
	(37, (0.63, 0.31, 0.02, 0.92), _SW_HEAD),
	(14, (0.72, 0.6, 0.02, 0.92), _SW_MID),
	(33, (0.75, 0.7, 0.02, 0.92), _SW_TAIL),
	(43, (0.89, 1.0, 0.02, 0.92), _SW_TAIL),
	(45, (1.06, 1.12, 0.02, 0.92), _SW_TAIL),
	(0, (1.4, 1.3, 0.02, 0.92), _SW_FADE),
)
# (pause before, keyframes) of the four sweeps that run side by side
_SW_SWEEPS = ((35, _SW_A), (215, _SW_B), (417, _SW_C), (571, _SW_D))


def half_value(color):
	"""G HUB's colour at half its HSV value (0x1410f78d0 x 0.5, rebuilt by FUN_1410f6380)."""
	return tuple(int(c * 0.5) for c in color[:3]) + tuple(color[3:])


def layout_leds(layout):
	"""(leds [(id, x, y)] in 0-1, accent ids, indicator ids) from a per-key layout (perkey.py);
	G HUB's two extra LED groups taken as the branding and indicator keys (ours)."""
	w, h, keys = layout
	leds = [(f'{g}:{k}', (x + kw / 2) / w, (y + kh / 2) / h) for g, k, x, y, kw, kh in keys
	        if g in softlight.KEY_GROUPS]
	accent = [f'{g}:{k}' for g, k, *_r in keys if g == 'PERKEY_BRANDING']
	indicator = [f'{g}:{k}' for g, k, *_r in keys if g == 'PERKEY_INDICATOR']
	return leds, accent, indicator


def smooth_wave(leds, accent=(), indicator=(), c1=(0, 127, 255, 255), c2=(255, 255, 255, 255)):
	"""G HUB's Smooth Wave as a handler tree. leds = [(id, x, y)] in 0-1 coordinates; accent and
	indicator = led ids of G HUB's two other LED groups (metadata +0x100 / +0x110; which LEDs
	those are isn't read yet: ours). Default colours are ours."""
	off = (0, 0, 0, 0)
	names = {C1: tuple(c1), C2H: half_value(c2), BLUE: (0xAF, 0xC9, 0xD5, 0xFF), OFF: off}

	def frames(kfs):
		return [(n, line, [(p, names[c], b) for p, c, b in stops]) for n, line, stops in kfs]
	area = (0.0, 0.0, 1.0, 1.0)
	ids = [led for led, _x, _y in leds]
	main = Parallelizer([ColorBlend(ids, off, off, 794)] + [
		Sequencer([Pause(pause), GradientTween(leds, area, frames(kfs), clip=True)])
		for pause, kfs in _SW_SWEEPS])
	accent_seq = Sequencer([ColorBlend(accent, off, c1, 100), Pause(200), ColorBlend(accent, c1, off, 97),
	                        Pause(200), ColorBlend(accent, off, c2, 100), ColorBlend(accent, c2, off, 97)])
	pulse = [Pause(100), ColorBlend(indicator, off, c1, 100), Pause(100), ColorBlend(indicator, c1, off, 97)]
	indicator_seq = Sequencer(pulse + [Pause(100), ColorBlend(indicator, off, c1, 100), Pause(100),
	                                   ColorBlend(indicator, c1, off, 97)])
	return Parallelizer([main, Parallelizer([accent_seq, indicator_seq])])


# --- Smooth Star (effect type SMOOTH_STAR = 14), G HUB's builder 0x141218ff0 ------------------
# Gradient keyframes (frames, stops) swept left to right (angle 0), looping; C2 = the effect's second
# colour (metadata +0xd8), OFF = G HUB's runtime constant (transparent black here, ours), the
# other colours are G HUB's own (exact, from the builder's disassembly).
C2 = 'C2'
_SS_KEYFRAMES = (
	(53, ((0, C2, 0.413), (1.0, C2, 0.5))),
	(51, ((0, C2, 0.5), (0.21, OFF, 0.67), (0.67, C2, 0.5), (1.0, OFF, 0.5))),
	(49, ((0, C2, 0.5), (0.3, (42, 58, 59, 255), 0.5), (0.63, (47, 65, 66, 255), 0.5), (0.79, C2, 0.5),
	      (0.95, OFF, 0.5), (1.0, OFF, 0.5))),
	(38, ((0, C2, 0.5), (0.07, (45, 63, 64, 255), 0.5), (0.25, C2, 0.5), (0.52, (85, 118, 120, 255), 0.5),
	      (0.71, OFF, 0.5), (1.0, OFF, 0.5))),
	(19, ((0, OFF, 0.5), (0.09, C2, 0.5), (0.25, C2, 0.5), (0.55, (85, 118, 120, 255), 0.5), (0.71, OFF, 0.5),
	      (0.8, OFF, 0.5), (0.91, C2, 0.5), (1.0, OFF, 0.5))),
	(21, ((0, OFF, 0.5), (0.04, C2, 0.5), (0.25, (14, 22, 23, 255), 0.5), (0.46, (77, 125, 128, 255), 0.5),
	      (0.6, OFF, 0.5), (0.8, (93, 152, 156, 255), 0.5), (0.91, C2, 0.5), (1.0, OFF, 0.5))),
	(27, ((0, OFF, 0.5), (0.13, (66, 107, 110, 255), 0.5), (0.25, (14, 22, 23, 255), 0.5),
	      (0.46, (77, 125, 128, 255), 0.5), (0.64, C2, 0.5), (0.78, (90, 147, 150, 255), 0.5), (0.91, OFF, 0.5),
	      (1.0, C2, 0.5))),
	(26, ((0, OFF, 0.5), (0.13, (66, 107, 110, 255), 0.5), (0.25, C2, 0.5), (0.47, (13, 13, 13, 255), 0.5),
	      (0.64, OFF, 0.5), (0.78, (98, 160, 163, 255), 0.5), (0.91, OFF, 0.5), (1.0, C2, 0.5))),
)
STAR_BLUE = (0, 184, 252, 255)          # G HUB's twinkle colour in Smooth Star (fixed)


def smooth_star(leds, logo=(), c1=(0, 0, 0, 255), c2=STAR_BLUE, rng=None):
	"""G HUB's Smooth Star for per-key keyboards (its root at metadata +0x1a0): a startup glow from
	the top centre, then the gradient sweep with twinkles over it. LED groups +0xe0 / +0xf0 /
	+0x100 taken as all keys and +0x110 as the logo (ours); default colours are ours."""
	off = (0, 0, 0, 0)
	c1, c2 = tuple(c1), tuple(c2)
	frames = [(n, 0.0, [(p, c2 if c == C2 else off if c == OFF else c, b) for p, c, b in stops])
	          for n, stops in _SS_KEYFRAMES]
	ids = [led for led, _x, _y in leds]
	return Sequencer([
		Startup(leds, leds, c1, c2, 18),
		Parallelizer([Gradient(leds, (0.0, 0.0, 1.0, 1.0), frames, loop=True),
		              Starlight(ids, STAR_BLUE, 0, 37, 31, 20, rng=rng),
		              ColorBlend(list(logo), c1, c1, 1, loop=True)])])


def dim(color, k):
	"""G HUB's brightness scale (FUN_1410f70c0): r, g, b x k, clamped; alpha kept."""
	return tuple(min(255, int(c * k)) for c in color[:3]) + tuple(color[3:])


def stops(*items):
	"""A gradient's stops sorted by position, as G HUB's gradient constructor (FUN_142a46680 ->
	FUN_142a463a0) does."""
	return sorted(items, key=lambda s: s[0])


def pulsar_point(leds, logo=(), indicator=(), c1=(0, 127, 255, 255), c2=(0, 127, 255, 255)):
	"""G HUB's Pulsar Point (signature style 1, per-key case in 0x1412084c0): a pulse of the colour
	with two dim bands sweeping across the keys, looping. Its colour is the second one (G HUB uses
	the first only for a device kind with LED group +0x108 and +0xe4 == 0x80); the logo keeps the
	first colour and the indicators the pulse colour (LED groups +0x118 / +0x128: ours)."""
	c = tuple(c2)
	band = stops((0, c, 0.5), (1.0, c, 0.5), (0.5, c, 0.5), (0.25, dim(c, 0.25), 0.5), (0.75, dim(c, 0.25), 0.5))
	keyframes = [(69, (-1.0287, 0.9531, 1.0032, 0.9698), band), (1, (-0.0033, 1.0015, 2.0339, 1.0268), band)]
	children = [GradientTween(leds, (0.0, 0.0, 1.0, 1.0), keyframes, loop=True, clip=True),
	            ColorBlend(list(logo), tuple(c1), tuple(c1), 60, loop=True)]
	if indicator:
		children.append(ColorBlend(list(indicator), c, c, 60, loop=True))
	return Parallelizer(children)


def remind_me_of(leds, c1=(255, 64, 0, 255)):
	"""G HUB's Remind Me Of (signature style 3, per-key case in 0x1412084c0): a band of the colour
	sweeps in from the left, then one from the right (each 30 frames, clipped). One colour (the
	effect's first); logo and indicators aren't part of it in G HUB."""
	c = tuple(c1)
	off = (0, 0, 0, 0)
	band = stops((0, c, 0.5), (1.0, off, 0.5), (0.4, dim(c, 0.8), 0.5), (0.3, c, 0.5), (0.94, off, 0.5))
	area = (0.0, 0.0, 1.0, 1.0)
	left = [(30, (-0.4269, 0.4743, 0.1159, 0.4743), band), (1, (0.7233, 0.4536, 1.0368, 0.4564), band)]
	right = [(30, (1.4622, 0.5138, 0.8992, 0.512), band), (1, (0.2519, 0.4937, -0.0406, 0.491), band)]
	return Sequencer([Parallelizer([GradientTween(leds, area, left, clip=True)]),
	                  Parallelizer([GradientTween(leds, area, right, clip=True)])])


def g_3_series(leds, c1=(255, 0, 80, 255), c2=(0, 90, 255, 255)):
	"""G HUB's G 3 Series (signature style 2, per-key case in 0x1412084c0): a vertical gradient that
	breathes from the second colour at the centre to the first and back (two gradients of 4
	keyframes each, run one after the other). D1 / D2 = the colours at 70 %."""
	a, b = tuple(c1), tuple(c2)
	d1, d2 = dim(a, 0.7), dim(b, 0.7)
	up = math.pi / 2                            # G HUB's 1.57
	centre_b = stops((0, d1, 0.5), (0.14, d2, 0.33), (0.5, b, 0.66), (0.86, d2, 0.5), (1.0, d1, 0.5))
	centre_a = stops((0, d2, 0.5), (0.14, d1, 0.5), (0.49, a, 0.5), (0.86, d1, 0.5), (1.0, d2, 0.5))
	to_a = [(15, up, centre_b),
	        (30, up, stops((0, d2, 0.5), (0.23, b, 0.5), (0.37, d2, 0.5), (0.5, d1, 0.5), (0.63, d2, 0.5),
	                       (0.77, b, 0.5), (1.0, d2, 0.5))),
	        (30, up, stops((0, b, 0.5), (0.19, d2, 0.5), (0.37, d1, 0.5), (0.5, a, 0.5), (0.63, d1, 0.5),
	                       (0.81, d2, 0.5), (1.0, b, 0.5))),
	        (30, up, centre_a)]
	to_b = [(15, up, centre_a),
	        (30, up, stops((0, d1, 0.5), (0.23, a, 0.5), (0.37, d1, 0.5), (0.5, d2, 0.5), (0.63, d1, 0.5),
	                       (0.77, a, 0.5), (1.0, d1, 0.5))),
	        (30, up, stops((0, a, 0.5), (0.19, d1, 0.5), (0.37, d2, 0.5), (0.5, b, 0.5), (0.62, d2, 0.5),
	                       (0.81, d1, 0.5), (1.0, a, 0.5))),
	        (30, up, centre_b)]
	area = (0.0, 0.0, 1.0, 1.0)
	return Sequencer([Gradient(leds, area, to_a), Gradient(leds, area, to_b)])


# Neon's steps (signature style 4): (frames, brightness) = the colour at that brightness, -n = a
# pause of n frames (G HUB's sequence, re/notes/signature_neon_sequence.txt)
_NEON = ((20, 1), -2, (1, 0.9), -3, (1, 0.5), -1, (1, 0.9), -3, (1, 0.8), -1, (1, 0.7), -2, -1, (1, 0.5), -2,
         (1, 0.6), -2, (1, 0.7), -1, (1, 0.8), -3, (1, 0.9), -1, (1, 0.8), -2, (1, 0.5), -3, (1, 0.7), -2,
         (1, 0.6), -3, (1, 1), -57, (1, 0.8), -1, (1, 0.8), -2, (1, 0.7), -1, (1, 0.6), -3, (1, 0.5), -1,
         (1, 0.8), -2, (1, 0.5), -3, (1, 0.7), -2, (1, 1), -42, (1, 0.7), -3, (1, 0.6), -2, (1, 1), -73,
         (1, 0.5), -3, (1, 0.9), -1, (1, 0.8), -2, (1, 0.7), -3, (1, 0.6), -1, (1, 0.5), -2, (1, 0.9), -3,
         (1, 0.8), -1, (1, 1), -25)


def neon(leds, c1=(255, 0, 200, 255)):
	"""G HUB's Neon (signature style 4, per-key case in 0x1412084c0): the keys flicker like a neon
	tube at G HUB's brightness steps, then hold, in one sequence."""
	ids = [led for led, _x, _y in leds]
	c = tuple(c1)
	steps = [Pause(-s) if isinstance(s, int) else ColorBlend(ids, dim(c, s[1]), dim(c, s[1]), s[0]) for s in _NEON]
	return Sequencer(steps)


# Outer Space's steps (signature style 5): (frames, on) - G HUB's sequence of the colour and off,
# 3- and 9-frame flashes like Morse code (re/notes/signature_outer_space_sequence.txt)
_OUTER_SPACE = ((40, 0), (3, 1), (3, 0), (9, 1), (3, 0), (3, 1), (3, 0), (3, 1), (9, 0), (9, 1), (3, 0), (9, 1),
                (3, 0), (9, 1), (9, 0), (9, 1), (3, 0), (9, 1), (3, 0), (9, 0), (3, 1), (3, 0), (3, 1), (30, 0))


def outer_space(leds, c1=(120, 0, 255, 255)):
	"""G HUB's Outer Space (signature style 5, per-key case in 0x1412084c0): the keys flash the
	colour in G HUB's on / off rhythm."""
	ids = [led for led, _x, _y in leds]
	c, off = tuple(c1), (0, 0, 0, 0)
	return Sequencer([ColorBlend(ids, c if on else off, c if on else off, n) for n, on in _OUTER_SPACE])


# name -> build(leds, logo ids, indicator ids, c1, c2), for lightsync
EFFECTS = {
	'smooth_wave': lambda leds, logo, ind, c1, c2: smooth_wave(leds, logo, ind, c1, c2),
	'smooth_star': lambda leds, logo, _ind, c1, c2: smooth_star(leds, logo, c1, c2),
	'pulsar_point': pulsar_point,
	'remind_me_of': lambda leds, _logo, _ind, c1, _c2: remind_me_of(leds, c1),
	'g_3_series': lambda leds, _logo, _ind, c1, c2: g_3_series(leds, c1, c2),
	'neon': lambda leds, _logo, _ind, c1, _c2: neon(leds, c1),
	'outer_space': lambda leds, _logo, _ind, c1, _c2: outer_space(leds, c1),
}


class Player:
	"""Steps a handler tree at FPS and restarts it when it ends (ours); frame(seconds) -> {led: rgb},
	like softlight's effects."""

	def __init__(self, build):
		self.build = build
		self.tree = build()
		self.steps = 0
		self.colors = {}

	def frame(self, t):
		target = int(t * FPS)
		while self.steps < target:
			f = Frame()
			if not self.tree.step(f):
				self.tree = self.build()
			self.colors.update(f.colors)
			self.steps += 1
		return {led: tuple(c[:3]) for led, c in self.colors.items()}


class ColorBlend:
	def __init__(self, leds, start, end, frames, easing=0, loop=False, reverse=False):
		self.leds, self.start, self.end, self.frames = leds, start, end, frames
		self.curve, self.loop, self.reverse = curve(easing), loop, reverse
		self.count = 0

	def reset(self):
		self.count = 0

	def step(self, frame):
		if self.count >= self.frames:
			if not self.loop:
				return False
			self.count = 0
		t = self.count / max(1, self.frames - 1)
		if self.reverse:
			t = 1 - t
		color = lerp(self.start, self.end, self.curve(t))
		for led in self.leds:
			frame.set(led, color)
		self.count += 1
		return True
