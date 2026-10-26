"""The newer headsets' stored lighting effects (0x0621, cluster_effects.py), in G HUB's byte order."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import cluster_effects as ce  # noqa: E402


class FakeHeadset:
	"""Two clusters; cluster 0 keeps fixed, cycle and breathing, its current effect breathing."""

	def __init__(self):
		self.calls = []

	def call(self, feature, fn, params=b''):
		self.calls.append((feature, fn, bytes(params)))
		if fn == ce.INFO:
			return bytes([0, 2, 1, 0, 2, 0]) + bytes(10)
		if fn == ce.CLUSTER_INFO:
			return bytes([3, 0, 0, 0, 1, 0, 1, 0, 0xF, 0, 3, 0, 7]) + bytes(3)
		if fn == ce.GET:
			return bytes([params[0], 0, 3, 10, 20, 30, 80, 0x13, 0x88]) + bytes(7)
		return bytes(16)


class ClusterEffectsTest(unittest.TestCase):
	def test_read(self):
		self.assertEqual(ce.read(FakeHeadset()), [
			(0, [0, 1, 3], (ce.BREATHING, {'color': (10, 20, 30), 'intensity': 80, 'period': 5000})),
			(1, [0, 1, 3], (ce.BREATHING, {'color': (10, 20, 30), 'intensity': 80, 'period': 5000}))])

	def test_encode_mirrors_g_hub(self):
		self.assertEqual(ce.encode(1, ce.FIXED, {'color': (1, 2, 3)}), bytes([1, 0, 0, 1, 2, 3, 0, 0, 0, 0]))
		self.assertEqual(ce.encode(0, ce.CYCLE, {'period': 0x1234, 'intensity': 50, 'saturation': 90}),
		                 bytes([0, 0, 1, 50, 0x12, 0x34, 90, 0, 0, 0]))
		self.assertEqual(ce.encode(0, ce.WAVE, {'period': 300, 'intensity': 100, 'direction': 3}),
		                 bytes([0, 0, 2, 100, 1, 44, 100, 3, 0, 0]))
		self.assertEqual(ce.encode(0, ce.BREATHING, {'color': (9, 8, 7), 'intensity': 40, 'period': 0x0102}),
		                 bytes([0, 0, 3, 9, 8, 7, 40, 1, 2, 0]))
		self.assertEqual(ce.encode(0, ce.SIGNATURE, {'color': (1, 2, 3), 'color2': (4, 5, 6), 'intensity': 7}),
		                 bytes([0, 0, 4, 1, 2, 3, 4, 5, 6, 7]))
		with self.assertRaises(ValueError):
			ce.encode(0, ce.CUSTOM, {})

	def test_round_trip(self):
		for eid, params in ((ce.FIXED, {'color': (5, 6, 7)}),
		                    (ce.WAVE, {'intensity': 60, 'period': 4000, 'saturation': 100, 'direction': 2}),
		                    (ce.SIGNATURE, {'color': (1, 2, 3), 'color2': (4, 5, 6), 'intensity': 70})):
			self.assertEqual(ce.decode(ce.encode(0, eid, params)), (eid, params))

	def test_set_effect(self):
		dev = FakeHeadset()
		ce.set_effect(dev, 1, ce.FIXED, {'color': (0, 0, 0)})
		self.assertEqual(dev.calls, [(ce.FEATURE, ce.SET, bytes([1, 0, 0, 0, 0, 0, 0, 0, 0, 0]))])


if __name__ == '__main__':
	unittest.main()
