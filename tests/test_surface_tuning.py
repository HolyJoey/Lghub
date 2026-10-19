import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hidpp  # noqa: E402
import simulate  # noqa: E402
import surface_tuning  # noqa: E402

# A Logitech-style mouse: report 2 = 16 buttons, X / Y 16-bit relative, wheel, AC pan
MOUSE = bytes([
	0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x02, 0x09, 0x01, 0xA1, 0x00,
	0x05, 0x09, 0x19, 0x01, 0x29, 0x10, 0x15, 0x00, 0x25, 0x01, 0x95, 0x10, 0x75, 0x01, 0x81, 0x02,
	0x05, 0x01, 0x16, 0x01, 0x80, 0x26, 0xFF, 0x7F, 0x75, 0x10, 0x95, 0x02, 0x09, 0x30, 0x09, 0x31,
	0x81, 0x06,
	0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x01, 0x09, 0x38, 0x81, 0x06,
	0x05, 0x0C, 0x0A, 0x38, 0x02, 0x95, 0x01, 0x81, 0x06,
	0xC0, 0xC0])


class FakeMotion:
	def __init__(self):
		self.lock = threading.Lock()
		self._d = 0.0

	@property
	def distance(self):
		self._d += 5.0
		return self._d


class SurfaceTuningTest(unittest.TestCase):
	def test_motion_fields(self):
		fields = surface_tuning.motion_fields(MOUSE)
		self.assertEqual(fields, {2: {'x': (16, 16, True), 'y': (32, 16, True)}})
		report = bytes([2, 0, 0]) + (-300).to_bytes(2, 'little', signed=True) + (25).to_bytes(2, 'little') + b'\0\0'
		self.assertEqual(surface_tuning.read_motion(fields, report), (-300, 25))
		self.assertIsNone(surface_tuning.read_motion(fields, bytes([5, 1, 2])))

	def test_hint(self):
		self.assertEqual(surface_tuning.speed_hint(2), surface_tuning.FASTER)
		self.assertEqual(surface_tuning.speed_hint(10), surface_tuning.GOOD)
		self.assertEqual(surface_tuning.speed_hint(30), surface_tuning.SLOWER)

	def test_tune(self):
		fake = simulate.FakeWheelMouse()
		dev = hidpp.Device(fake)
		seen = []
		with mock.patch.object(surface_tuning, 'WINDOW', 0.001):
			values = surface_tuning.tune(dev, FakeMotion(), lambda f, s, h: seen.append(f), threading.Event())
		self.assertEqual(values, [42, 7, 30])
		self.assertEqual(fake.tuning, [2, 3, 4, 5, 6, 1])        # G HUB's order, then the values
		self.assertEqual(fake.surface, [42, 7, 30])
		self.assertEqual(seen[-1], 1.0)
		self.assertTrue(all(a <= b for a, b in zip(seen, seen[1:])))

	def test_info(self):
		fake = simulate.FakeWheelMouse()
		dev = hidpp.Device(fake)
		surface_tuning.apply(dev, [42, 7, 30])
		self.assertEqual(surface_tuning.info(dev), ([42, 7, 30], [20, 5, 25]))

	def test_cancel_still_ends_tuning(self):
		fake = simulate.FakeWheelMouse()
		cancel = threading.Event()
		cancel.set()
		dev, motion = hidpp.Device(fake), FakeMotion()
		with self.assertRaises(surface_tuning.Cancelled):
			surface_tuning.tune(dev, motion, lambda *_: None, cancel)
		self.assertEqual(fake.tuning, [2, 3, 6])


if __name__ == '__main__':
	unittest.main()
