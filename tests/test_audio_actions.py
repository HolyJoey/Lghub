import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import audio_actions  # noqa: E402
import eq  # noqa: E402
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

	def test_wpctl_actions_and_unknown(self):
		self.assertTrue(audio_actions.run('VOLUME_UP'))
		audio_actions.subprocess.run.assert_called_with(
			['wpctl', 'set-volume', '-l', '1.0', '@DEFAULT_AUDIO_SINK@', '5%+'], capture_output=True)
		self.assertFalse(audio_actions.run('NOPE'))


if __name__ == '__main__':
	unittest.main()
