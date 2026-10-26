import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import audio_actions  # noqa: E402
import eq  # noqa: E402
import hidpp  # noqa: E402
import pw  # noqa: E402
import simulate  # noqa: E402
import surround  # noqa: E402


class AudioActionsTest(unittest.TestCase):
	def setUp(self):
		self.notes = []
		patches = [mock.patch.object(audio_actions, '_notify', lambda title, body, *_a: self.notes.append((title, body))),
		           mock.patch('subprocess.run')]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_next_after_wraps_and_starts_at_first(self):
		self.assertEqual(audio_actions.next_after(['a', 'b'], 'b'), 'a')
		self.assertEqual(audio_actions.next_after(['a', 'b'], 'x'), 'a')
		self.assertIsNone(audio_actions.next_after([], 'a'))

	def test_equalizer_cycle_turns_on_next_preset(self):
		saved = {}
		names = list(eq.PRESETS)
		with mock.patch.object(eq, 'load', return_value={'enabled': True, 'preset': names[0], 'gains': []}), \
				mock.patch.object(eq, 'save', saved.update):
			audio_actions.run('EQUALIZER_CYCLE')
		expected = names[1 % len(names)]
		self.assertEqual((saved['enabled'], saved['preset']), (True, expected))
		self.assertEqual(saved['gains'], list(eq.PRESETS[expected]))
		self.assertEqual(self.notes, [('Equalizer', expected)])

	def test_equalizer_off_starts_at_first_preset(self):
		saved = {}
		with mock.patch.object(eq, 'load', return_value={'enabled': False, 'preset': 'Flat', 'gains': []}), \
				mock.patch.object(eq, 'save', saved.update):
			audio_actions.cycle_equalizer()
		self.assertEqual(saved['preset'], list(eq.PRESETS)[0])

	def test_surround_toggle(self):
		saved = {}
		with mock.patch.object(surround, 'load', return_value={'enabled': False}), \
				mock.patch.object(surround, 'save', saved.update):
			audio_actions.run('SURROUND_TOGGLE')
		self.assertTrue(saved['enabled'])
		self.assertEqual(self.notes, [('Surround sound', 'On')])

	def test_output_cycle_sets_next_default(self):
		sinks = [{'id': 40, 'name': 'a', 'description': 'Speakers'}, {'id': 41, 'name': 'b', 'description': 'Headset'}]
		with mock.patch.object(eq, 'sinks', return_value=sinks), \
				mock.patch.object(audio_actions, 'default_name', return_value='a'):
			audio_actions.run('AUDIO_OUTPUT_CYCLE')
		audio_actions.subprocess.run.assert_called_with(['wpctl', 'set-default', '41'], capture_output=True)
		self.assertEqual(self.notes, [('Audio output', 'Headset')])

	def test_headset_steps(self):
		fake = simulate.FakeEqHeadset()
		with mock.patch.object(audio_actions, '_headsets', return_value=['headset']), \
				mock.patch('devices.open_hidpp', side_effect=lambda _d: hidpp.Device(fake)):
			audio_actions.run('BASS_INCREASE')
			self.assertEqual(fake.bass, 60)
			fake.bass = 95
			audio_actions.run('BASS_INCREASE')
			self.assertEqual(fake.bass, 100)                         # kept within 0-100
			audio_actions.run('SIDETONE_DECREASE')                    # no headset has sidetone: nothing
		self.assertEqual(self.notes, [('Bass', '60 %'), ('Bass', '100 %')])

	def test_equalizer_toggle_and_make_default(self):
		saved = {}
		with mock.patch.object(eq, 'load', return_value={'enabled': True}), mock.patch.object(eq, 'save', saved.update):
			audio_actions.run('ADVANCED_EQUALIZER_TOGGLE')
		self.assertFalse(saved['enabled'])
		sinks = [{'id': 40, 'name': 'alsa_output.pci', 'description': 'Speakers'},
		         {'id': 41, 'name': 'alsa_output.usb-Logitech_G733', 'description': 'G733'}]
		with mock.patch.object(eq, 'sinks', return_value=sinks), mock.patch.object(pw, 'sources', return_value=[]):
			audio_actions.run('MAKE_DEFAULT_AUDIO_DEVICE')
		audio_actions.subprocess.run.assert_called_with(['wpctl', 'set-default', '41'], capture_output=True)
		self.assertEqual(self.notes[-1], ('Audio device', 'G733'))

	def test_wpctl_actions_and_unknown(self):
		self.assertTrue(audio_actions.run('VOLUME_UP'))
		audio_actions.subprocess.run.assert_called_with(
			['wpctl', 'set-volume', '-l', '1.0', '@DEFAULT_AUDIO_SINK@', '5%+'], capture_output=True)
		self.assertFalse(audio_actions.run('NOPE'))


if __name__ == '__main__':
	unittest.main()


class AudioHelpersTest(unittest.TestCase):
	def test_default_name_from_wpctl(self):
		out = 'id 57, type PipeWire:Interface:Node\n  * node.name = "alsa_output.usb-Logitech_PRO_X"\n    media.class = "Audio/Sink"\n'
		with mock.patch('subprocess.run', return_value=mock.Mock(stdout=out)):
			self.assertEqual(audio_actions.default_name('SINK'), 'alsa_output.usb-Logitech_PRO_X')
		with mock.patch('subprocess.run', return_value=mock.Mock(stdout='nothing\n')):
			self.assertIsNone(audio_actions.default_name('SINK'))
		with mock.patch('subprocess.run', side_effect=OSError):
			self.assertIsNone(audio_actions.default_name('SOURCE'))

	def test_cycle_device(self):
		nodes = [{'id': 1, 'name': 'a', 'description': 'A'}, {'id': 2, 'name': 'b', 'description': 'B'}]
		with mock.patch('subprocess.run') as run:
			self.assertEqual(audio_actions.cycle_device(nodes, 'a')['id'], 2)
			self.assertEqual(run.call_args[0][0], ['wpctl', 'set-default', '2'])
			self.assertIsNone(audio_actions.cycle_device([], 'a'))

	def test_headsets_behind_receivers(self):
		import types
		model = lambda t: types.SimpleNamespace(type=t)              # noqa: E731
		receiver = types.SimpleNamespace(model=model('receiver'))
		dead = types.SimpleNamespace(model=model('receiver'))
		corded = types.SimpleNamespace(model=model('headset'))
		paired = types.SimpleNamespace(model=model('headset'))
		mouse = types.SimpleNamespace(model=model('mouse'))

		def scan(r):
			if r is dead:
				raise OSError('gone')
			return [paired, mouse]
		with mock.patch('devices.discover', return_value=[receiver, dead, corded, mouse]), \
		     mock.patch('devices.scan_receiver', side_effect=scan):
			self.assertEqual(list(audio_actions._headsets()), [paired, corded])

	def test_step_skips_headsets_that_do_not_answer(self):
		with mock.patch.object(audio_actions, '_headsets', return_value=['a']), \
		     mock.patch('devices.open_hidpp', side_effect=OSError('busy')):
			self.assertIsNone(audio_actions.step_headset(0x8300, 5))
