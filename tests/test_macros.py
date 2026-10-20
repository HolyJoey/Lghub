"""Macros in G HUB's format, played on a fake output that records what would be typed."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import macros  # noqa: E402
import uinput  # noqa: E402


class FakeOut:
	def __init__(self):
		self.events = []

	def usage(self, usage, down, consumer=False):
		self.events.append(('media' if consumer else 'key', usage, down))
		return True

	def key(self, code, down):
		self.events.append(('code', code, down))

	def tap(self, code):
		self.key(code, True)
		self.key(code, False)

	def wheel(self, clicks, horizontal=False):
		self.events.append(('wheel', clicks, horizontal))


class MacroTest(unittest.TestCase):
	def setUp(self):
		self.out = FakeOut()
		self.device = []
		self.run_ = macros.Runner(self.out, lambda kind, action, down: self.device.append((kind, action, down)))

	def test_keystroke_follows_the_button(self):
		m = macros.keystroke(0x06, [macros.CTRL])
		self.run_.press(1, m)
		self.assertEqual(self.out.events, [('key', 0xe0, True), ('key', 0x06, True)])
		self.run_.release(1, m)
		self.assertEqual(self.out.events[2:], [('key', 0x06, False), ('key', 0xe0, False)])
		self.assertEqual(macros.describe(m), 'Ctrl + C')

	def test_text_block(self):
		self.run_.press(1, {'type': 'TEXT_BLOCK', 'text_block': {'text': 'Hi!'}})
		self.assertEqual(self.out.events, [('key', 0xe1, True), ('key', 0x0b, True), ('key', 0x0b, False),
		                                   ('key', 0xe1, False), ('key', 0x0c, True), ('key', 0x0c, False),
		                                   ('key', 0xe1, True), ('key', 0x1e, True), ('key', 0x1e, False),
		                                   ('key', 0xe1, False)])

	def test_sequence_with_delay(self):
		seq = {'type': 'SEQUENCE', 'name': 'Reload', 'sequence': {'use_simple_actions': True, 'simple_sequence': {
			'components': [{'keyboard': {'hid_usage': 0x15, 'is_down': True}}, {'delay': {'duration_ms': 30}},
			               {'keyboard': {'hid_usage': 0x15, 'is_down': False}}]}}}
		self.run_.press(1, seq)
		time.sleep(0.15)
		self.assertEqual(self.out.events, [('key', 0x15, True), ('key', 0x15, False)])
		self.assertEqual(macros.describe(seq), 'Reload')

	def test_toggle_repeats_until_pressed_again(self):
		seq = {'type': 'SEQUENCE', 'sequence': {'use_toggle_actions': True, 'toggle_sequence': {
			'components': [{'keyboard': {'hid_usage': 0x2c, 'is_down': True}},
			               {'keyboard': {'hid_usage': 0x2c, 'is_down': False}}, {'delay': {'duration_ms': 10}}]}}}
		self.run_.press(1, seq)
		time.sleep(0.08)
		self.run_.press(1, seq)
		count = len(self.out.events)
		time.sleep(0.05)
		self.assertGreater(count, 4)
		self.assertLessEqual(len(self.out.events) - count, 2)   # stopped (at most the step in flight)

	def test_media_and_device_actions(self):
		m = {'type': 'MEDIA', 'media': {'usage': 'VOLUME_UP'}}
		self.run_.press(1, m)
		self.run_.release(1, m)
		self.assertEqual(self.out.events, [('media', 0xe9, True), ('media', 0xe9, False)])
		self.run_.press(2, {'type': 'MOUSE', 'mouse': {'action': 'DPI_CYCLE'}})
		self.assertEqual(self.device, [('MOUSE', 'DPI_CYCLE', True)])

	def test_mouse_button(self):
		m = {'type': 'MOUSE', 'mouse': {'action': 'BUTTON', 'hid_usage': 4}}
		self.run_.press(1, m)
		self.run_.release(1, m)
		self.assertEqual(self.out.events, [('code', uinput.BTN_SIDE, True), ('code', uinput.BTN_SIDE, False)])

	def test_one_shot_actions(self):
		with mock.patch.object(macros, '_spawn') as spawn:
			self.run_.press(1, {'type': 'APP', 'app': {'executable_path': '/bin/foo', 'argument_list': ['-x']}})
			self.run_.press(1, {'type': 'OPEN_WEB_PAGE', 'open_web_page': {'url': 'https://example.org'}})
			self.run_.press(1, {'type': 'SYSTEM', 'system': {'action': 'LOCK'}})
		self.assertEqual([c.args[0] for c in spawn.call_args_list],
		                 [['/bin/foo', '-x'], ['xdg-open', 'https://example.org'], ['loginctl', 'lock-session']])
		self.run_.press(1, {'type': 'SYSTEM', 'system': {'action': 'COPY'}})
		self.assertEqual(self.out.events, [('key', macros.CTRL, True), ('key', 0x06, True), ('key', 0x06, False),
		                                   ('key', macros.CTRL, False)])
		self.out.events.clear()
		self.run_.press(1, {'type': 'SYSTEM', 'system': {'action': 'BRIGHTNESS_UP'}})
		self.run_.press(1, {'type': 'SYSTEM', 'system': {'action': 'SCROLL_LEFT'}})
		self.assertEqual(self.out.events, [('media', 0x6f, True), ('media', 0x6f, False), ('wheel', -1, True)])
		self.run_.press(1, {'type': 'DEVICE', 'device': {'action': 'PROFILE_CYCLE'}})
		self.assertEqual(self.device, [('DEVICE', 'PROFILE_CYCLE', True)])

	def test_audio_action_runs_in_the_background(self):
		with mock.patch('audio_actions.run') as run:
			self.run_.press(1, {'type': 'AUDIO', 'audio': {'action': 'SURROUND_TOGGLE'}})
			time.sleep(0.05)
		run.assert_called_once_with('SURROUND_TOGGLE')

	def test_press_held_release_sequence(self):
		down = {'keyboard': {'hid_usage': 0x04, 'is_down': True}}
		up = {'keyboard': {'hid_usage': 0x04, 'is_down': False}}
		seq = {'type': 'SEQUENCE', 'sequence': {'use_simple_actions': False,
		                                        'press_sequence': {'components': [down]},
		                                        'held_sequence': {'components': [{'delay': {'duration_ms': 5}}]},
		                                        'release_sequence': {'components': [up]}}}
		self.run_.press(1, seq)
		self.assertIn(1, self.run_.held)
		self.run_.release(1, seq)
		time.sleep(0.05)
		self.assertEqual(self.out.events, [('key', 0x04, True), ('key', 0x04, False)])
		self.assertNotIn(1, self.run_.held)

	def test_held_repeats_until_released(self):
		seq = macros.sequence_macro([{'keyboard': {'hid_usage': 0x05, 'is_down': True}},
		                             {'keyboard': {'hid_usage': 0x05, 'is_down': False}},
		                             {'delay': {'duration_ms': 5}}], mode='held')
		self.run_.press(1, seq)
		time.sleep(0.05)
		self.run_.release(1, seq)
		count = len(self.out.events)
		time.sleep(0.03)
		self.assertGreater(count, 2)
		self.assertLessEqual(len(self.out.events) - count, 2)

	def test_default_delay_and_nested_components(self):
		seq = macros.sequence_macro([{'media': {'usage': 'STOP'}}, {'mouse': {'button': {'hid_usage': 1}}},
		                             {'mouse': {'wheel': {'is_positive': False}}}], keep_delays=False)
		seq['sequence']['default_delay'] = 1
		self.run_.play(seq['sequence']['simple_sequence'], seq['sequence'])
		self.assertEqual(self.out.events, [('media', 0xb7, True), ('media', 0xb7, False),
		                                   ('code', uinput.BTN_LEFT, True), ('wheel', -1, False)])

	def test_double_click_and_wheel(self):
		self.run_.press(1, {'type': 'MOUSE', 'mouse': {'action': 'BUTTON_DOUBLE_CLICK', 'hid_usage': 1}})
		self.run_.press(1, {'type': 'MOUSE', 'mouse': {'action': 'WHEEL_LEFT'}})
		self.assertEqual(self.out.events, [('code', uinput.BTN_LEFT, True), ('code', uinput.BTN_LEFT, False)] * 2
		                 + [('wheel', -1, True)])

	def test_describe_and_key_names(self):
		cases = {'Type “hello”': {'type': 'TEXT_BLOCK', 'text_block': {'text': 'hello'}},
		         'Play pause': {'type': 'MEDIA', 'media': {'usage': 'PLAY_PAUSE'}},
		         'Mouse button 4': {'type': 'MOUSE', 'mouse': {'action': 'BUTTON', 'hid_usage': 4}},
		         'Dpi cycle': {'type': 'MOUSE', 'mouse': {'action': 'DPI_CYCLE'}},
		         'Run /bin/foo': {'type': 'APP', 'app': {'executable_path': '/bin/foo'}},
		         'Open x.org': {'type': 'OPEN_WEB_PAGE', 'open_web_page': {'url': 'x.org'}},
		         'Macro': {'type': 'SEQUENCE'}, 'Disabled': {}, 'Something new': {'type': 'SOMETHING_NEW'}}
		for text, macro in cases.items():
			self.assertEqual(macros.describe(macro), text)
		self.assertEqual([macros.key_name(u) for u in (0x1e, 0x27, 0x3a, 0x68, 0x2c, 0xe0, 0x99)],
		                 ['1', '0', 'F1', 'F13', 'Space', uinput.MODIFIER_USAGES[0xe0], 'Key 0x99'])
		self.assertTrue(macros.is_device_action({'type': 'MOUSE', 'mouse': {'action': 'DPI_UP'}}))
		self.assertFalse(macros.is_device_action({'type': 'MOUSE', 'mouse': {'action': 'BUTTON'}}))


class LibraryTest(unittest.TestCase):
	def test_library_round_trip_and_recording(self):
		tmp = tempfile.mkdtemp()
		with mock.patch.object(macros, 'LIBRARY_FILE', os.path.join(tmp, 'm.json')), \
				mock.patch.object(macros, 'ASSIGNMENTS_FILE', os.path.join(tmp, 'a.json')):
			self.assertEqual(macros.library(), {})
			macros.save_library({'m1': {'type': 'MEDIA'}})
			self.assertEqual(macros.new_id(macros.library()), 'm2')
			macros.save_assignments({'dev': {'button:4': 'm1'}})
			self.assertEqual(macros.assignments(), {'dev': {'button:4': 'm1'}})
		m = macros.recorded_sequence([(0x04, True, 1.0), (0x04, False, 1.25)], mode='toggle')
		self.assertTrue(m['sequence']['use_toggle_actions'])
		self.assertEqual(macros.sequence_components(m), [{'keyboard': {'hid_usage': 4, 'is_down': True}},
		                                                 {'delay': {'duration_ms': 250}},
		                                                 {'keyboard': {'hid_usage': 4, 'is_down': False}}])


if __name__ == '__main__':
	unittest.main()
