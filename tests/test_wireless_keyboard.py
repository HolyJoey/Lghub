"""Receivers, model matching and keyboard features against the simulated devices."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import devices  # noqa: E402
import features  # noqa: E402
import hidpp  # noqa: E402
import perkey  # noqa: E402
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


class YetiTest(unittest.TestCase):
	def test_polar_pattern(self):
		yeti = simulate.FakeYeti()
		dev = hidpp.Device(yeti)
		self.assertEqual(features.polar_patterns(dev), ([1, 2, 3, 4], 2))
		features.set_polar_pattern(dev, 4)
		self.assertEqual(yeti.pattern, 4)
		self.assertEqual(features.PATTERNS[4], 'Omnidirectional')


class PerKeyTest(unittest.TestCase):
	def test_zone_table(self):
		# G HUB's default table: A, the last usage before the gap, a modifier, media keys, G1, logo
		self.assertEqual(perkey.zone_for(perkey.KEYBOARD, 0x04), 1)
		self.assertEqual(perkey.zone_for(perkey.KEYBOARD, 0x65), 0x62)
		self.assertEqual(perkey.zone_for(perkey.KEYBOARD, 0xE0), 0x68)
		self.assertEqual(perkey.zone_for(perkey.CONSUMER, 0xB5), 0x9D)
		self.assertEqual(perkey.zone_for(perkey.CONSUMER, 0xCD), 0x9B)
		self.assertEqual(perkey.zone_for(perkey.CONSUMER, 0xE2), 0x9C)
		self.assertIsNone(perkey.zone_for(perkey.CONSUMER, 0xE3))
		self.assertEqual(perkey.zone_for(perkey.GKEY, 1), 0xB4)
		self.assertEqual(perkey.zone_for(perkey.BRANDING, 1), 0xD2)
		self.assertEqual(perkey.zone_for(perkey.INDICATOR, 1), 0x99)
		self.assertEqual(perkey.zone_for(perkey.INDICATOR, 3), 0x96)
		self.assertIsNone(perkey.zone_for(8, 1))

	def test_apply(self):
		kb = simulate.FakeKeyboard()
		colors = {f'PERKEY_KEYBOARD:{k}': [k, 0, 255] for k in range(4, 14)}
		colors['PERKEY_GKEY:1'] = [1, 2, 3]
		colors['PERKEY_GENERIC:1'] = [9, 9, 9]
		self.assertEqual(perkey.apply(hidpp.Device(kb), colors), 11)
		self.assertEqual(kb.keys[1], (4, 0, 255))
		self.assertEqual(kb.keys[10], (13, 0, 255))
		self.assertEqual(kb.keys[0xB4], (1, 2, 3))
		self.assertEqual(len(kb.keys), 11)
		self.assertTrue(kb.persisted)
