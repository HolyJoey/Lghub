"""Macros in G HUB's format, played on a fake output that records what would be typed."""
import os
import sys
import time
import unittest

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


if __name__ == '__main__':
	unittest.main()
