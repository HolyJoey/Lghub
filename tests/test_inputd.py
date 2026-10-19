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


class DeviceActionTest(unittest.TestCase):
	"""G HUB's DPI and profile macro actions on a simulated G502 (factory profile 1: 400-6400 DPI)."""

	def setUp(self):
		self.fake = simulate.FakeMouse()
		self.actions = inputd.DeviceActions(hidpp.Device(self.fake))

	def test_dpi_steps_onboard(self):
		self.fake.mode, self.fake.dpi_slot = 1, 1
		self.actions('MOUSE', 'DPI_UP')
		self.assertEqual(self.fake.dpi_slot, 2)
		self.actions('MOUSE', 'DPI_DOWN')
		self.actions('MOUSE', 'DPI_DOWN')
		self.actions('MOUSE', 'DPI_DOWN')
		self.assertEqual(self.fake.dpi_slot, 0)            # stops at the lowest
		self.fake.dpi_slot = 4
		self.actions('MOUSE', 'DPI_CYCLE')
		self.assertEqual(self.fake.dpi_slot, 0)            # cycles round

	def test_dpi_shift_host_mode(self):
		self.fake.mode, self.fake.dpi = 2, 1600
		self.actions('MOUSE', 'DPI_SHIFT', True)
		shifted = self.fake.dpi
		self.actions('MOUSE', 'DPI_SHIFT', False)
		self.assertEqual(self.fake.dpi, 1600)              # back after release
		self.assertIn(shifted, (400, 800, 1600, 3200, 6400))

	def test_profiles(self):
		self.fake.mode, self.fake.profile = 1, 1
		self.actions('DEVICE', 'PROFILE_NEXT')
		self.assertEqual(self.fake.profile, 2)
		self.actions('DEVICE', 'PROFILE_CYCLE')
		self.actions('DEVICE', 'PROFILE_CYCLE')
		self.assertEqual(self.fake.profile, 1)
		self.actions('DEVICE', 'PROFILE_PREV')
		self.assertEqual(self.fake.profile, 1)             # no wrap backwards from the first

	def test_runner_passes_release(self):
		calls = []
		runner = macros.Runner(out=Recorder(), device_action=lambda *a: calls.append(a))
		m = {'type': 'MOUSE', 'mouse': {'action': 'DPI_SHIFT'}}
		runner.press('button:6', m)
		runner.release('button:6', m)
		self.assertEqual(calls, [('MOUSE', 'DPI_SHIFT', True), ('MOUSE', 'DPI_SHIFT', False)])
		self.assertTrue(macros.is_device_action(m))


class MKeyTest(unittest.TestCase):
	def test_g_keys_follow_the_m_set(self):
		kb = simulate.FakeKeyboard()
		dev = hidpp.Device(kb)
		runner = Recorder()
		m1, m2 = {'type': 'TEXT_BLOCK', 'text_block': {'text': 'one'}}, {'type': 'TEXT_BLOCK', 'text_block': {'text': 'two'}}
		calls = []
		runner_obj = macros.Runner(out=runner)
		runner_obj.press = lambda key, macro: calls.append(('press', key, macro['text_block']['text']))
		runner_obj.release = lambda key, macro: calls.append(('release', key, macro['text_block']['text']))
		di = inputd.DeviceInput(dev, {'gkey:1': m1, 'm2:gkey:1': m2}, runner_obj)
		self.assertTrue(di.start())
		self.assertTrue(kb.gkeys_software)
		self.assertEqual(kb.m_led, 1)
		kb.event(0x8020, [2])          # M2 pressed
		kb.event(0x8010, [1])          # G1 down
		kb.event(0x8010, [0])          # G1 up
		deadline = time.time() + 2
		while len(calls) < 2 and time.time() < deadline:
			time.sleep(0.02)
		di.stop()
		self.assertEqual(kb.m_led, 2)
		self.assertEqual(calls, [('press', 'm2:gkey:1', 'two'), ('release', 'm2:gkey:1', 'two')])
		self.assertFalse(kb.gkeys_software)
