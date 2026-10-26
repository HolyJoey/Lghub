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

	def test_startup_glows_from_the_top_centre(self):
		group2 = [('top', 0.5, 0.0), ('corner', 0.0, 1.0)]
		s = sig.Startup([], group2, RED, BLUE, 4)
		for _ in range(3):
			f = sig.Frame()
			s.step(f)
		self.assertGreater(f.colors['top'][2], f.colors['corner'][2])   # closer to B at the top centre

	def test_starlight_twinkles(self):
		import random
		star = sig.Starlight(['a', 'b', 'c'], BLUE, 0, 37, 31, 20, rng=random.Random(1))
		lit = set()
		for _ in range(200):
			f = sig.Frame()
			star.step(f)
			lit.update(k for k, c in f.colors.items() if c[2])
		self.assertEqual(lit, {'a', 'b', 'c'})
		self.assertLessEqual(len(star.stars), 20)

	def test_smooth_star_runs(self):
		import random
		leds = [(f'PERKEY_KEYBOARD:{30 + x * 5 + y}', x / 9, y / 4) for x in range(10) for y in range(5)]
		leds += [('PERKEY_KEYBOARD:26', 0.2, 0.4), ('PERKEY_COSMETIC:160', 0.5, 0.0), ('PERKEY_BRANDING:1', 0.5, 1.0)]
		tree = sig.smooth_star(leds, c1=(200, 0, 0, 255), rng=random.Random(2))
		lit, w, strip = set(), set(), []
		for _ in range(500):
			f = sig.Frame()
			self.assertTrue(tree.step(f))                      # loops (the gradient and stars run on)
			lit.update(k for k, c in f.colors.items() if any(c[:3]))
			if 'PERKEY_KEYBOARD:26' in f.colors:
				w.add(f.colors['PERKEY_KEYBOARD:26'])
			if 'PERKEY_COSMETIC:160' in f.colors:
				strip.append(f.colors['PERKEY_COSMETIC:160'])
		self.assertGreater(len(lit), 40)
		self.assertIn((200, 0, 0, 255), w)                     # W held at colour one (G HUB's WASD group)
		self.assertEqual(len(strip), 18)                       # the strip only glows in the startup

	def test_pulsar_point_sweeps(self):
		leds = [(f'PERKEY_KEYBOARD:{30 + x}', x / 9, 0.5) for x in range(10)]
		leds += [('PERKEY_KEYBOARD:4', 0.1, 0.6), ('PERKEY_BRANDING:1', 0.5, 0.9)]
		tree = sig.pulsar_point(leds, c2=(0, 100, 200, 255))
		seen = {}
		for _ in range(70):
			f = sig.Frame()
			self.assertTrue(tree.step(f))
			for k, c in f.colors.items():
				seen.setdefault(k, set()).add(c[2])
		self.assertGreater(len(seen['PERKEY_KEYBOARD:35']), 3)        # the key's brightness changes as bands pass
		self.assertEqual(seen['PERKEY_KEYBOARD:4'], {sig.GHUB_PINK[2]})  # A keeps the first colour (WASD group)
		self.assertEqual(seen['PERKEY_BRANDING:1'], {200})              # the logo takes the pulse colour
		self.assertEqual(sig.stops((1, 'b', 0.5), (0, 'a', 0.5))[0][1], 'a')

	def test_neon_flickers_then_holds(self):
		tree = sig.neon([('k', 0.5, 0.5)], c1=(200, 0, 100, 255))
		levels, steps = [], 0
		while tree.step(f := sig.Frame()):
			if 'k' in f.colors:
				levels.append(f.colors['k'][0])
			steps += 1
		# each child also takes the frame in which it reports it is done (G HUB's sequencer)
		self.assertEqual(steps, sum(s[0] if isinstance(s, tuple) else -s for s in sig._NEON) + len(sig._NEON))
		self.assertEqual(set(levels), {200, 180, 160, 140, 120, 100})

	def test_remind_me_of_and_g3(self):
		leds = [(f'k{x}', x / 9, 0.5) for x in range(10)]
		for name, build in sig.EFFECTS.items():
			tree = build(leds, ['logo'], ['ind'], (200, 0, 0, 255), (0, 0, 200, 255))
			self.assertIn(name, ('smooth_wave', 'smooth_star', 'pulsar_point', 'remind_me_of', 'g_3_series', 'neon',
			                     'outer_space', 'g_tide'))
			for _ in range(120):
				tree.step(sig.Frame())

	def test_g_tide_grows_sweeps_and_shrinks(self):
		ids = sorted({k for group in sig._G_TIDE_LISTS for k in group})
		leds = [(f'PERKEY_KEYBOARD:{k}', (k % 20) / 19, (k // 20) / 11) for k in ids] + [('PERKEY_KEYBOARD:250', 0, 0)]
		rings = sig.g_tide_rings(leds)
		self.assertEqual([len(r) for r in rings], [len(set(g)) for g in sig._G_TIDE_LISTS])   # G HUB's lists
		self.assertIn('PERKEY_KEYBOARD:154', rings[0])
		tree = sig.g_tide(leds, c1=(200, 0, 0, 255), c2=(0, 0, 200, 255))
		first, steps, colors = [], 0, {}
		while tree.step(f := sig.Frame()):
			if steps < 5:
				first.append(set(f.colors))
			colors.update(f.colors)
			steps += 1
			self.assertLess(steps, 1000)
		self.assertEqual(first[0], set(rings[0]))
		# each sampler takes one more frame to report it is done, like the Sequencer's other children
		self.assertEqual(steps, sum(n + 1 for *_r, n in sig._G_TIDE_OUT + sig._G_TIDE_BACK) + 121 + 1)
		self.assertEqual(colors['PERKEY_KEYBOARD:250'][:3], (0, 0, 0))     # ends black outside the lists
		self.assertIn('g_tide', sig.EFFECTS)

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


class SignatureCatalogTest(unittest.TestCase):
	def test_colours_and_effects_from_g_hubs_device_list(self):
		import json
		import tempfile
		from unittest import mock
		import depots
		import lightsync
		dev = {'modelId': 'g512_x_75', 'capabilities': {'lightingSupport': {'zones': [{'supportedEffects': [
			{'id': 'SIGNATURE_ALGORITHMIC_ACTIVE', 'signature': True, 'name': 'REMIND_ME_OF',
			 'signatureSupport': {'signatureColorOne': {'hex': '#FF0000'}}},
			{'id': 'FIXED'}]}]}}}
		out = {}
		depots._signature_colors(dev, out)
		self.assertEqual(out, {'g512_x_75': {'remind_me_of': ['#FF0000', None],
		                                    '_ids': {'SIGNATURE_ALGORITHMIC_ACTIVE': 'remind_me_of'}}})
		with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
			json.dump(out, f)
		try:
			with mock.patch.object(depots, 'signature_colors_path', return_value=f.name):
				self.assertEqual(lightsync.signature_defaults('g512_x_75', 'remind_me_of'),
				                 ((255, 0, 0), lightsync.GHUB_BLUE))
				self.assertEqual(lightsync.signature_effects('g512_x_75'), ['remind_me_of'])
				self.assertIsNone(lightsync.signature_effects('g815'))
				self.assertEqual(lightsync.signature_defaults('g815', 'neon'), (lightsync.GHUB_PINK, lightsync.GHUB_BLUE))
				self.assertEqual(lightsync.firmware_signature('g512_x_75'), 'remind_me_of')
				self.assertIsNone(lightsync.firmware_signature('g815'))
		finally:
			os.unlink(f.name)
