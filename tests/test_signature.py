"""G HUB's signature effect engine: gradient sampling, blends and the frame handlers."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import signature as sig  # noqa: E402

RED, BLUE = (255, 0, 0, 255), (0, 0, 255, 255)
STOPS = [(0.0, RED, 0.5), (1.0, BLUE, 0.5)]


class SignatureTest(unittest.TestCase):
	def test_easing_order_is_qt(self):
		self.assertEqual(sig.EASINGS[:5], ['LINEAR', 'INQUAD', 'OUTQUAD', 'INOUTQUAD', 'OUTINQUAD'])
		self.assertEqual(sig.EASINGS[36], 'OUTINBACK')
		self.assertAlmostEqual(sig.curve(1)(0.5), 0.25)

	def test_lerp_truncates(self):
		self.assertEqual(sig.lerp((0, 0, 0, 0), (255, 10, 3, 255), 0.5), (127, 5, 1, 127))
		self.assertEqual(sig.lerp(RED, BLUE, 0), RED)
		self.assertEqual(sig.lerp(RED, BLUE, 1.5), BLUE)

	def test_bezier_with_even_bias_is_linear(self):
		for u in (0.0, 0.25, 0.5, 0.75, 1.0):
			self.assertAlmostEqual(sig.bezier(0.5, 0.5, u), u, places=3)
		self.assertLess(sig.bezier(0.9, 0.1, 0.5), 0.5)       # bias toward the start colour

	def test_sample(self):
		self.assertEqual(sig.sample(STOPS, -1), RED)
		self.assertEqual(sig.sample(STOPS, 2), BLUE)
		mid = sig.sample(STOPS, 0.5)
		self.assertTrue(120 <= mid[0] <= 128 and 120 <= mid[2] <= 128)

	def test_pause_and_sequencer(self):
		seq = sig.Sequencer([sig.Pause(2), sig.Pause(1)])
		running = [seq.step(sig.Frame()) for _ in range(6)]
		self.assertEqual(running, [True] * 5 + [False])

	def test_parallelizer_runs_while_any_runs(self):
		par = sig.Parallelizer([sig.Pause(1), sig.Pause(3)])
		self.assertEqual([par.step(sig.Frame()) for _ in range(4)], [True, True, True, False])

	def test_gradient_sweeps_across_the_area(self):
		leds = [('left', 0.0, 0.5), ('right', 1.0, 0.5)]
		g = sig.Gradient(leds, (0.0, 0.0, 1.0, 1.0), [(10, 0.0, STOPS)])
		f = sig.Frame()
		self.assertTrue(g.step(f))
		self.assertEqual(f.colors['left'], RED)
		self.assertEqual(f.colors['right'], BLUE)
		g = sig.Gradient(leds, (0.0, 0.0, 1.0, 1.0), [(10, math.pi, STOPS)])
		f = sig.Frame()
		g.step(f)
		self.assertEqual(f.colors['right'], RED)                  # angle pi: projection < 0 -> first stop

	def test_gradient_tween_band(self):
		leds = [('a', 0.1, 0.5), ('b', 0.9, 0.5), ('out', 0.0, 0.5)]
		line = (0.05, 0.5, 0.95, 0.5)
		tw = sig.GradientTween(leds, (0.0, 0.0, 1.0, 1.0), [(4, line, STOPS), (4, line, STOPS)])
		f = sig.Frame()
		tw.step(f)
		self.assertGreater(f.colors['a'][0], f.colors['a'][2])     # near the start: red
		self.assertGreater(f.colors['b'][2], f.colors['b'][0])     # near the end: blue
		self.assertEqual(f.colors['out'], (0, 0, 0, 0))

	def test_color_blend(self):
		blend = sig.ColorBlend(['k'], RED, BLUE, 3)
		colors = []
		for _ in range(3):
			f = sig.Frame()
			blend.step(f)
			colors.append(f.colors['k'])
		self.assertEqual(colors[0], RED)
		self.assertEqual(colors[-1], BLUE)
		self.assertFalse(blend.step(sig.Frame()))

	def test_smooth_wave_runs_and_colours_the_keys(self):
		leds = [(f'k{x}{y}', x / 9, y / 4) for x in range(10) for y in range(5)]
		tree = sig.smooth_wave(leds, accent=['logo'], indicator=['ind'], c1=(0, 127, 255, 255))
		lit, steps = set(), 0
		while tree.step(f := sig.Frame()):
			lit.update(k for k, c in f.colors.items() if any(c[:3]))
			steps += 1
			self.assertLess(steps, 2000)
		self.assertGreaterEqual(steps, 794)                 # the background blend's length
		self.assertLessEqual({'logo', 'ind'}, lit)
		self.assertGreater(len(lit), 20)                    # the sweeps reach most of the keys

	def test_player_restarts(self):
		calls = []

		def build():
			calls.append(1)
			return sig.Pause(2)
		p = sig.Player(build)
		p.frame(1.0)                                        # 30 steps
		self.assertGreater(len(calls), 5)

	def test_brightness(self):
		f = sig.Frame(brightness=50)
		f.set('k', (200, 100, 0, 255))
		self.assertEqual(f.colors['k'], (100, 50, 0, 255))
