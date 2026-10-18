"""Software buttons over 0x8110, against the simulated mouse."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hidpp  # noqa: E402
import inputd  # noqa: E402
import macros  # noqa: E402
import simulate  # noqa: E402


class Recorder:
	def __init__(self):
		self.calls = []

	def press(self, key, macro):
		self.calls.append(('press', key, macro['name']))

	def release(self, key, macro):
		self.calls.append(('release', key, macro['name']))


class SpyTest(unittest.TestCase):
	def test_only_assigned_buttons_leave_the_mouse(self):
		fake = simulate.FakeMouse()
		dev = hidpp.Device(fake)
		rec = Recorder()
		macro = dict(macros.keystroke(0x06, [macros.CTRL]), name='Copy')
		d = inputd.DeviceInput(dev, {'button:6': macro}, rec)
		self.assertTrue(d.start())
		self.assertTrue(fake.spying)
		self.assertEqual(fake.remap[5], 0)                       # button 6 handled in software
		self.assertEqual(fake.remap[:5], bytes([1, 2, 3, 4, 5]))  # left, right, ... still native
		fake.press(1 << 5)
		time.sleep(0.3)
		fake.press(0)
		time.sleep(0.3)
		fake.press(1 << 0)     # left click: not assigned, ignored here
		time.sleep(0.3)
		d.stop()
		self.assertEqual(rec.calls, [('press', 'button:6', 'Copy'), ('release', 'button:6', 'Copy')])
		self.assertFalse(fake.spying)
		self.assertEqual(fake.remap, bytes(range(1, 17)))         # restored

	def test_nothing_assigned_does_nothing(self):
		fake = simulate.FakeMouse()
		d = inputd.DeviceInput(hidpp.Device(fake), {}, Recorder())
		self.assertFalse(d.start())
		self.assertFalse(fake.spying)

	def test_resolve_skips_deleted_macros(self):
		lib = {'m1': {'name': 'A'}}
		self.assertEqual(inputd.resolve({'button:4': 'm1', 'button:5': 'gone'}, lib), {'button:4': {'name': 'A'}})


if __name__ == '__main__':
	unittest.main()
