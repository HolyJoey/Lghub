"""The device page's cards (hidpp_panel.py): built from what a device reports, and every control sends
the request its feature module builds. Needs a display (GDK_BACKEND=broadway works); skipped without one."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
	import gi
	gi.require_version('Gtk', '4.0')
	from gi.repository import Gtk
	HAVE_DISPLAY = Gtk.init_check()
except (ImportError, ValueError):
	HAVE_DISPLAY = False


class FakeDev:
	"""Answers every request with zeros and keeps what was sent."""

	def __init__(self):
		self.calls = []

	def has(self, _feature):
		return True

	def call(self, feature, fn, params=b''):
		self.calls.append((feature, fn, bytes(params)))
		return bytes(16)


class SyncWorker:
	def submit(self, job, done=None, failed=None):
		try:
			result = job()
		except Exception as e:            # noqa: BLE001 - the page shows the error the same way
			if failed:
				failed(e)
			return
		if done:
			done(result)


def info():
	import cluster_effects
	import features
	import mouse
	led = mouse.Led.build_v2(mouse.LED_FIXED, (1, 2, 3))
	return {
		'name': 'Test device', 'battery': (80, 'Discharging'), 'firmware': '1.2', 'life': None,
		'features': [0x0000, 0x8070, 0x8100, 0x8300],
		'zones': [features.Zone(0, 1, [(0, 1), (1, 4), (2, 24)])],
		'brightness': (50, 100), 'rates': [125, 500, 1000], 'rate': 1000, 'sidetone': 30,
		'patterns': ([1, 2], 2), 'angle_snapping': True, 'fn_inversion': (True, False),
		'analog': {'rapid_trigger': True, 'key_priority': False},
		'analog_profile': {'actuation': 1.5, 'keys': {0: 1.2}, 'rapid': {0: 0.3}, 'pairs': [(0, 1, 'distance', True)]},
		'analog_cids': [0x10, 0x20],
		'light': {'on': True, 'brightness': 100, 'brightness_range': (20, 250, 1), 'temperature': 4000,
		          'temperature_range': (2700, 6500, 100)},
		'game_mode': (4, [0xE3], [(0xE3, 'Left Windows'), (0x39, 'Caps Lock')]),
		'hosts': (3, 0), 'host_names': ['Desk', None],
		'device_eq': {'on': True, 'gains': [0, 2], 'freqs': [100, 2000], 'low': -12, 'high': 12},
		'charging': True, 'bass_tone': 40,
		'mic': {'muted': False, 'centurion': True, 'gain': 5, 'gain_range': (0, 10), 'plugged': True,
		        'headphones': 50, 'monitoring': 20},
		'anc': (1, [0, 1], 2), 'onboard_eq': [(100, 0, 7), (1000, 2, 7)],
		'headset_switches': {0x060E: True, 0x0618: False, 'ai_level': 2},
		'mic_select': (['Headset mic (wireless)', 'USB mic'], 0), 'aux': 1, 'usb_ports': [(0, 0), (1, 1)],
		'tone_sets': ([0, 1], 1), 'mix': (5, 10, 'Bluetooth 1', 'Lightspeed 1'),
		'macros': [(1, 'Hi', bytes([0x43, 0, 4, 0x40, 0, 50, 0x44, 0, 4, 0xFF]))],
		'onboard_profile': {'name': 'P1', 'wired': 1000, 'wireless': 500, 'game_mode': [0x10],
		                    'immersive': (True, [('active', 0, led)])},
		'key_rows': ([('Base', [(0, [(0, 0, 0, 0x8002, 4), (1, 0x20, 0, 0x9003, 0)])])], [0x10]),
		'clusters': [(0, [0, 1, 2, 3, 4, 5], (cluster_effects.WAVE, {'intensity': 50, 'period': 3000,
		                                                              'saturation': 100, 'direction': 1}))],
		'fkc': True, 'power': {1: 300, 2: 900}, 'mode': mouse.MODE_ONBOARD, 'profiles': (3, 2),
	}


def poke(widget):
	"""Change every control under widget once, as a person would."""
	from gi.repository import Gdk
	if isinstance(widget, Gtk.Switch):
		widget.set_active(not widget.get_active())
	elif isinstance(widget, Gtk.DropDown):
		n = widget.get_model().get_n_items()
		widget.set_selected((widget.get_selected() + 1) % n if n else 0)
	elif isinstance(widget, Gtk.Scale):
		adj = widget.get_adjustment()
		widget.set_value(adj.get_upper() if widget.get_value() != adj.get_upper() else adj.get_lower())
	elif isinstance(widget, Gtk.ColorDialogButton):
		rgba = Gdk.RGBA()
		rgba.parse('#123456')
		widget.set_rgba(rgba)
	elif isinstance(widget, Gtk.Button) and widget.get_sensitive() and widget.get_label():
		widget.emit('clicked')
	if isinstance(widget, (Gtk.DropDown, Gtk.ColorDialogButton, Gtk.Scale, Gtk.Switch)):
		return                            # their insides open popups
	child = widget.get_first_child()
	while child is not None:
		poke(child)
		child = child.get_next_sibling()


@unittest.skipUnless(HAVE_DISPLAY, 'needs a display')
class PanelCardsTest(unittest.TestCase):
	def setUp(self):
		import hidpp_panel
		import store
		self.tmp = tempfile.TemporaryDirectory()
		self.patches = [mock.patch.object(store, 'CONFIG_DIR', self.tmp.name),
		                mock.patch.object(store, 'save_config'), mock.patch.object(store, 'load_config', return_value={})]
		for p in self.patches:
			p.start()
		panel = hidpp_panel.SettingsPanel.__new__(hidpp_panel.SettingsPanel)
		Gtk.Box.__init__(panel, orientation=Gtk.Orientation.VERTICAL)
		model = types.SimpleNamespace(key='test_kb', type='headset', lighting=['all'], flags=['onboard'])
		panel.win = types.SimpleNamespace(toast=lambda _t: None)
		panel.device = types.SimpleNamespace(model=model, name='Test device', usb_id='046d:0000')
		panel.on_status = lambda _t, _d: None
		panel.quiet, panel.host, panel.loading, panel.body = False, 0, False, panel
		panel.worker, panel.no_sidetone, panel.sidetone_elsewhere = SyncWorker(), None, False
		panel.dev = self.dev = FakeDev()
		self.panel = panel
		self.window = Gtk.Window(child=panel)

	def tearDown(self):
		for p in self.patches:
			p.stop()
		self.tmp.cleanup()

	def test_colour_buttons_start_with_the_colour(self):
		import hidpp_panel
		self.assertEqual(hidpp_panel._rgb(hidpp_panel._color_button((10, 20, 30))), (10, 20, 30))

	def test_every_card_builds_and_sends(self):
		self.panel._connected(info())
		titles = []
		child = self.panel.get_first_child()
		while child is not None:
			first = child.get_first_child()
			if isinstance(first, Gtk.Label):
				titles.append(first.get_text())
			child = child.get_next_sibling()
		for title in ('Brightness', 'Report rate', 'Sidetone', 'Mix', 'Voice prompts', 'Onboard macros',
		              'Active onboard profile', 'Onboard key assignments', 'Stored lighting', 'Noise cancelling',
		              'Headset equalizer', 'Easy-Switch', 'Power', 'On-board memory', 'What it reports'):
			self.assertIn(title, titles)
		with mock.patch('centurion_eq.coefficients', return_value=b''):
			poke(self.panel)
		sent = {(f, fn) for f, fn, _p in self.dev.calls}
		for want in ((0x1B05, 1), (0x0609, 1), (0x060B, 5), (0x0621, 3), (0x0605, 1), (0x063C, 1), (0x063A, 2), (0x063B, 2)):
			self.assertIn(want, sent)

	def test_no_hidpp_and_status(self):
		import hidpp_panel
		self.panel._no_hidpp(OSError('nothing'))
		self.panel.quiet = True
		self.panel._no_hidpp(OSError('nothing'))
		self.assertIn('Battery 80 %', hidpp_panel.SettingsPanel._status_text(info()))
		self.panel.set_sidetone_elsewhere(True)


if __name__ == '__main__':
	unittest.main()


@unittest.skipUnless(HAVE_DISPLAY, 'needs a display')
class MouseLedCardTest(unittest.TestCase):
	def _view(self, v2):
		import features
		import mouse
		import mouse_ui
		view = mouse_ui.MouseView.__new__(mouse_ui.MouseView)
		Gtk.Box.__init__(view)
		view.profiles, view.editing = [mouse.Profile(1, 0, True, bytearray(mouse.P_LEDS + mouse.LED_SIZE * 2 + 64))], 0
		view.mouse = types.SimpleNamespace(features={features.RGB_EFFECTS} if v2 else set())
		zone = features.Zone(0, 1, [(i, e) for i, e in enumerate(mouse.ONBOARD_V2_EFFECTS)], features.RGB_EFFECTS)
		view.state = {'zones': [zone]}
		view.loading = False
		view.changed = lambda: None
		return view

	def test_two_colour_entry_from_the_card(self):
		import mouse
		view = self._view(True)
		c = view._led_card(0, 'Logo')
		Gtk.Window(child=c)
		dropdown = next(w for w in _walk(c) if isinstance(w, Gtk.DropDown))
		dropdown.set_selected(list(view._led_effects(0, True)[0]).index(0x19))
		poke(c)
		led = view.profile.led(0)
		self.assertIn(led.effect, mouse.ONBOARD_V2_EFFECTS)

	def test_old_profile_card(self):
		import mouse
		view = self._view(False)
		c = view._led_card(0, 'Logo')
		Gtk.Window(child=c)
		poke(c)
		self.assertIn(view.profile.led(0).effect, mouse.LED_EFFECTS)


def _walk(widget):
	yield widget
	child = widget.get_first_child()
	while child is not None:
		yield from _walk(child)
		child = child.get_next_sibling()


@unittest.skipUnless(HAVE_DISPLAY, 'needs a display')
class ProEqCardTest(unittest.TestCase):
	def test_card_reads_switches_and_writes(self):
		from gi.repository import GLib
		import proeq
		import proeq_ui
		log = []

		class Chip:
			def __init__(self, *_a):
				pass

			def profile(self):
				return 1

			def bands(self, _p):
				return [(0, 100, 256, 0.0), (2, 4000, 256, 3.0)]

			def set_profile(self, p):
				log.append(('profile', p))

			def set_band_gain(self, p, band, gain):
				log.append(('gain', p, band, gain))

			def close(self):
				pass
		with mock.patch.object(proeq, 'find', return_value=('/dev/x', 64, 64)), mock.patch.object(proeq, 'Chip', Chip):
			card = proeq_ui.ProEqCard(types.SimpleNamespace(port='3-2'), SyncWorker())
			Gtk.Window(child=card)
			scale = next(w for w in _walk(card) if isinstance(w, Gtk.Scale))
			scale.set_value(5.0)
			scale.set_value(6.0)                      # the first write is replaced by the second
			ctx = GLib.MainContext.default()
			end = GLib.get_monotonic_time() + 2_000_000
			while not any(e[0] == 'gain' for e in log) and GLib.get_monotonic_time() < end:
				ctx.iteration(False)
			dropdown = next(w for w in _walk(card) if isinstance(w, Gtk.DropDown))
			dropdown.set_selected(3)
		self.assertIn(('gain', 1, 1, 6.0), log)
		self.assertIn(('profile', 3), log)

	def test_card_without_the_interface(self):
		import proeq
		import proeq_ui
		with mock.patch.object(proeq, 'find', return_value=None):
			card = proeq_ui.ProEqCard(types.SimpleNamespace(port='3-2'), SyncWorker())
		texts = [w.get_text() for w in _walk(card) if isinstance(w, Gtk.Label)]
		self.assertTrue(any('can’t read' in t for t in texts))


@unittest.skipUnless(HAVE_DISPLAY, 'needs a display')
class LightsyncCardTest(unittest.TestCase):
	def test_per_key_and_zone_cards_build(self):
		import lightsync_ui
		for per_key in (True, False):
			card = lightsync_ui.card('g815', lambda: None, per_key=per_key)
			self.assertIsInstance(card, Gtk.Widget)
