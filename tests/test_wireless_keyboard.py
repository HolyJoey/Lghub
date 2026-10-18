"""Receivers, model matching and keyboard features against the simulated devices."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import devices  # noqa: E402
import features  # noqa: E402
import hidpp  # noqa: E402
import simulate  # noqa: E402


class ReceiverTest(unittest.TestCase):
	def test_paired_devices(self):
		receiver = simulate.FakeReceiver()
		paired = features.paired_devices(lambda i: hidpp.Device(receiver, i))
		self.assertEqual([(p.index, p.kind) for p in paired], [(1, 'mouse')])
		self.assertEqual(paired[0].name, 'G502 LIGHTSPEED Wireless Gaming Mouse')

	def test_battery(self):
		receiver = simulate.FakeReceiver()
		self.assertEqual(features.battery(hidpp.Device(receiver, 1)), (72, 'On battery'))

	def test_match_model(self):
		self.assertEqual(devices.match_model('G502 LIGHTSPEED Wireless Gaming Mouse', 'mouse').key, 'g502_wireless')
		self.assertEqual(devices.match_model('G915 TKL LIGHTSPEED Wireless RGB Keyboard', 'keyboard').key,
		                 'g915_tkl')
		self.assertEqual(devices.match_model('Some new thing', 'mouse').type, 'mouse')


class KeyboardTest(unittest.TestCase):
	def setUp(self):
		self.kb = simulate.FakeKeyboard()
		self.dev = hidpp.Device(self.kb)

	def test_zones(self):
		zones = features.zones(self.dev)
		self.assertEqual([z.name for z in zones], ['Main', 'Logo'])
		self.assertIn((1, features.BREATHING), zones[0].effects)

	def test_set_effect(self):
		params = features.effect_params(features.FIXED, (1, 2, 3))
		features.set_effect(self.dev, 0, 0, params)
		self.assertEqual(self.kb.effects[0], (0, bytes([1, 2, 3]) + bytes(7)))

	def test_brightness(self):
		self.assertEqual(features.brightness(self.dev), (80, 100))
		features.set_brightness(self.dev, 25)
		self.assertEqual(features.brightness(self.dev)[0], 25)

	def test_short_reports_when_they_fit(self):
		sent = []
		write = self.kb.write
		self.kb.write = lambda msg: (sent.append(msg[0]), write(msg))
		dev = hidpp.Device(self.kb, reports={hidpp.SHORT, hidpp.LONG})
		dev.protocol_version()
		features.set_effect(dev, 0, 0, features.effect_params(features.FIXED))
		self.assertEqual(sent[0], hidpp.SHORT)
		self.assertEqual(sent[-1], hidpp.LONG)


if __name__ == '__main__':
	unittest.main()
