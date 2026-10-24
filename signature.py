"""G HUB's signature effect engine (Smooth Star, Smooth Wave, Pulsar Point, ... as software effects).

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
G HUB's per-effect builders (not ported yet).
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
