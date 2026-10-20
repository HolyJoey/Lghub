"""LIGHTSYNC's players: where colours go (zones, keys), and the loops that stream them."""
import io
import json
import math
import os
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import features  # noqa: E402
import lightsync  # noqa: E402
import mouse  # noqa: E402
import softlight  # noqa: E402

LAYOUT = (100, 100, [('PERKEY_KEYBOARD', 4, 0, 80, 10, 10), ('PERKEY_KEYBOARD', 5, 90, 0, 10, 10)])


class FakeTarget:
	def __init__(self, keys, zonal=False, fail_after=None):
		self.keys, self.zonal, self.sent, self.fail_after = keys, zonal, [], fail_after
		self.layout = None if zonal else LAYOUT
		self.done = threading.Event()

	def send(self, colors):
		self.sent.append(dict(colors))
		if self.fail_after and len(self.sent) >= self.fail_after:
			self.done.set()
			raise OSError('unplugged')


def player(cls, target, *args):
	with mock.patch.object(lightsync, 'make_target', return_value=target), \
			mock.patch.object(lightsync, 'PerKeyTarget', FakeTarget):
		return cls(mock.Mock(), 'g815', *args)


class TargetTest(unittest.TestCase):
	def test_zone_target_uses_each_zones_fixed_effect(self):
		zones = [features.Zone(0, 1, effects=[(0, features.CYCLE), (1, features.FIXED)]),
		         features.Zone(1, 2, effects=[(0, features.CYCLE)])]
		dev = mock.Mock()
		dev.has.return_value = True
		with mock.patch.object(features, 'zones', return_value=zones), \
				mock.patch.object(features, 'set_effect') as set_effect:
			target = lightsync.ZoneTarget(dev)
			target.send({'ZONE:0': [1, 2, 3]})
		self.assertEqual(target.keys, ['ZONE:0'])
		self.assertEqual(target.fixed['ZONE:0'][3], 'ZONE_PRIMARY')
		args = set_effect.call_args
		self.assertEqual(args.args[1:3], (0, 1))
		self.assertEqual(args.args[3][:3], bytes([1, 2, 3]))
		self.assertFalse(args.kwargs['persist'])

	def test_make_target(self):
		dev = mock.Mock()
		dev.has.side_effect = lambda f: f == lightsync.perkey.PERKEY
		with mock.patch.object(lightsync.perkey, 'load_layout', return_value=LAYOUT):
			self.assertIsInstance(lightsync.make_target(dev, 'g815'), lightsync.PerKeyTarget)
		dev.has.side_effect = lambda f: False
		with mock.patch.object(lightsync.perkey, 'load_layout', return_value=None):
			self.assertIsNone(lightsync.make_target(dev, 'x'))

	def test_restore_zones_reselects_the_profile(self):
		dev = mock.Mock()
		dev.has.return_value = True
		dev.call.return_value = bytes([0, 2])
		lightsync.restore_zones(dev)
		dev.call.assert_called_with(mouse.ONBOARD, 3, bytes([0, 2]))


class VisualizerLoopTest(unittest.TestCase):
	def run_visualizer(self, target, options=None):
		freqs = lightsync.band_freqs()
		samples = [0.5 * math.sin(2 * math.pi * freqs[0] * i / lightsync.RATE) for i in range(lightsync.FRAME * 3)]
		pcm = b''.join(struct.pack('<h', int(s * 32767)) for s in samples)
		v = player(lightsync.Visualizer, target, [200, 0, 0], options)
		v.proc = mock.Mock(stdout=io.BytesIO(pcm))
		with mock.patch.object(v, '_columns', return_value=None):
			v._run()
		return target.sent

	def test_zones_follow_the_loudness(self):
		sent = self.run_visualizer(FakeTarget(['ZONE:0'], zonal=True))
		self.assertTrue(sent)
		self.assertGreater(sent[0]['ZONE:0'][0], 100)

	def test_keys_follow_the_bands(self):
		sent = self.run_visualizer(FakeTarget(['PERKEY_KEYBOARD:4', 'PERKEY_KEYBOARD:5']))
		self.assertEqual(sent[0]['PERKEY_KEYBOARD:4'], [200, 0, 0])        # bass, bottom left: lit

	def test_start_needs_a_target(self):
		v = player(lightsync.Visualizer, None, [1, 1, 1])
		self.assertFalse(v.start())


class SamplerLoopTest(unittest.TestCase):
	def test_frames_until_the_screen_goes(self):
		target = FakeTarget(['PERKEY_KEYBOARD:4'], fail_after=None)
		s = player(lightsync.ScreenSampler, target, {'color_boost': 0, 'smoothing': True})
		pictures = [(2, 1, bytes([255, 0, 0, 255, 0, 0])), (2, 1, bytes([0, 0, 255, 0, 0, 255]))]

		def grab():
			if not pictures:
				raise OSError('screen gone')
			return pictures.pop(0)

		s.screen = None
		with mock.patch.object(s, '_ghub_regions', return_value=({'r': (0, 0, 1, 1)}, {'PERKEY_KEYBOARD:4': 'r'})), \
				mock.patch.object(s, '_grabber', return_value=grab), mock.patch.object(lightsync, 'SCREEN_FPS', 1000):
			s._run()
		self.assertEqual(target.sent[0], {'PERKEY_KEYBOARD:4': [255, 0, 0]})
		self.assertEqual(target.sent[1]['PERKEY_KEYBOARD:4'], [178, 0, 76])     # smoothed toward blue

	def test_frame_without_ghub_map(self):
		s = player(lightsync.ScreenSampler, FakeTarget(['ZONE:0'], zonal=True), {})
		s.layout = None
		self.assertEqual(s._frame({'BOTTOM_CENTER': [1, 2, 3]}, None), {'ZONE:0': [1, 2, 3]})


class AnimatedTest(unittest.TestCase):
	def test_make_each_kind(self):
		keys = ['PERKEY_KEYBOARD:4', 'PERKEY_KEYBOARD:5']
		target = FakeTarget(keys)
		for effect, cls in (('starlight', softlight.Starlight), ('echo', softlight.EchoPress),
		                    ('cycle', softlight.ColorCycle)):
			a = player(lightsync.Animated, target, {'effect': effect})
			self.assertIsInstance(a.make(), cls)
		with tempfile.TemporaryDirectory() as d:
			frames = {'keyframeInfo': {'speed': 10, 'keyframeMap': {'1': {'length': 5, 'lightingSlots': {'infoMap': {
				'PERKEY_KEYBOARD': {'perKeyMap': {'colorCodeMap': {'4': {'hex': '#00ff00'}, '99': {'hex': '#fff'}}}}}}}}}}
			with open(os.path.join(d, 'mine.json'), 'w') as f:
				json.dump(frames, f)
			with mock.patch.object(softlight, 'CUSTOM_DIR', d):
				effect = player(lightsync.Animated, target, {'effect': 'keyframe', 'custom': 'mine.json'}).make()
		self.assertEqual(effect.frame(0.0), {'PERKEY_KEYBOARD:4': [0, 255, 0]})     # keys it doesn't have dropped

	def test_run_sends_only_changes(self):
		target = FakeTarget(['PERKEY_KEYBOARD:4'], fail_after=3)
		a = player(lightsync.Animated, target, {'effect': 'cycle', 'speed': 1000})
		with mock.patch.object(lightsync, 'FPS', 200):
			a._run()
		self.assertEqual(len(target.sent), 3)

	def test_echo_follows_presses(self):
		target = FakeTarget(['ZONE:0', 'ZONE:1'], zonal=True)
		a = player(lightsync.Animated, target, {'effect': 'echo'}, 'usb-1')
		effect = mock.Mock()
		with mock.patch('keypress.Keys') as keys, mock.patch('keypress.key_nodes', return_value=[]):
			self.assertTrue(a._follow_presses(effect))
			keys.call_args.args[1](1)                         # a click
		self.assertEqual([c.args[0] for c in effect.press.call_args_list], ['ZONE:0', 'ZONE:1'])
		with mock.patch('keypress.Keys') as keys, mock.patch('keypress.key_nodes', return_value=[]):
			keys.return_value.start.side_effect = OSError('no access')
			self.assertFalse(a._follow_presses(effect))

	def test_unavailable_effect_stops_quietly(self):
		a = player(lightsync.Animated, FakeTarget(['PERKEY_KEYBOARD:4']), {'effect': 'keyframe', 'file': 'x.json'})
		with mock.patch.object(softlight, 'fetch', return_value='/nonexistent.json'):
			a._run()


class RunnerTest(unittest.TestCase):
	def test_starts_switches_and_stops(self):
		device = mock.Mock(id='usb:1', model=mock.Mock(key='g815'), port='1-2')
		device.name = 'G815'
		devices = mock.Mock()
		devices.discover.return_value = [device]
		runner = lightsync.Runner()
		made = []

		def fake(kind):
			def make(*args):
				v = mock.Mock(kind=kind, args=args, target=mock.Mock(zonal=False))
				v.start.return_value = True
				made.append(v)
				return v
			return make

		settings = {'g815': {'effect': 'screen'}}
		with mock.patch.dict(sys.modules, {'devices': devices}), \
				mock.patch.object(lightsync, 'devices_open', return_value=mock.Mock()), \
				mock.patch.object(lightsync, 'load', return_value=settings), \
				mock.patch.object(lightsync, 'ScreenSampler', fake('screen')), \
				mock.patch.object(lightsync, 'Animated', fake('animated')), \
				mock.patch.object(lightsync, 'Visualizer', fake('audio')), \
				mock.patch('restore.apply_saved') as apply_saved:
			runner.check(1.0)
			settings['g815'] = {'effect': 'starlight'}
			runner.check(2.0)                                 # the setting changed: restarted
			settings['g815'] = {'effect': 'audio'}
			runner.check(3.0)
			runner.stop()
		self.assertEqual([v.kind for v in made], ['screen', 'animated', 'audio'])
		self.assertEqual(made[1].args[3], '1-2')               # the echo effect gets the USB port
		self.assertEqual(apply_saved.call_count, 2)
		self.assertTrue(all(v.stop.called for v in made))
		self.assertEqual(runner.running, {})

	def test_due_when_the_file_changes(self):
		runner = lightsync.Runner()
		with tempfile.TemporaryDirectory() as d, mock.patch.object(lightsync, 'FILE', os.path.join(d, 'l.json')):
			self.assertTrue(runner.due(1000.0))
			runner.last = 1000.0
			self.assertFalse(runner.due(1000.0))
			with open(lightsync.FILE, 'w') as f:
				f.write('{}')
			self.assertTrue(runner.due(1000.0))


if __name__ == '__main__':
	unittest.main()
