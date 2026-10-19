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


class KeyboardSwitchTest(unittest.TestCase):
	def test_game_mode_and_fn(self):
		kb = simulate.FakeMultiHostKeyboard()
		dev = hidpp.Device(kb)
		self.assertEqual(features.max_disabled_keys(dev), 8)
		kb.disabled = {0x39}
		features.set_disabled_keys(dev, [0xE3, 0x65])
		self.assertEqual(kb.disabled, {0xE3, 0x65})        # all back on first, then the chosen ones
		features.set_disabled_keys(dev, [])
		self.assertEqual(kb.disabled, set())
		self.assertEqual(features.fn_inversion(dev, 1), (False, True))
		features.set_fn_inversion(dev, True, 1)
		self.assertEqual(features.fn_inversion(dev, 1), (True, True))
		self.assertEqual(features.hosts(dev), (3, 1))
		features.set_host(dev, 2)
		self.assertEqual([features.host_name(dev, h) for h in range(3)], ['desktop', 'my-laptop-running-linux', None])


class HeadsetEqTest(unittest.TestCase):
	def test_device_eq(self):
		hs = simulate.FakeEqHeadset()
		dev = hidpp.Device(hs)
		eq = features.device_eq(dev)
		self.assertEqual(eq, {'freqs': [80, 240, 750, 2200, 6600], 'gains': [0] * 5, 'low': -12, 'high': 12, 'on': True})
		features.set_device_eq(dev, [3, -2, 0, 1.4, -12])
		self.assertEqual((hs.lead, hs.gains), (2, [3, -2, 0, 1, -12]))   # G HUB's leading 2, whole dB
		self.assertEqual(features.bass_tone(dev), 50)
		features.set_bass_tone(dev, 140)
		self.assertEqual(hs.bass, 100)
		features.set_device_eq_on(dev, False)
		self.assertFalse(features.device_eq(dev)['on'])


class RgbEffectsTest(unittest.TestCase):
	def test_8071(self):
		m = simulate.FakeRgbMouse()
		dev = hidpp.Device(m)
		zones = features.zones_v2(dev)
		self.assertEqual([(z.name, z.feature) for z in zones], [('Main', 0x8071), ('Logo', 0x8071)])
		self.assertIn((1, features.BREATHING), zones[0].effects)
		params = features.effect_params(features.FIXED, (1, 2, 3))
		features.set_effect(dev, 1, 0, params, feature=zones[1].feature)
		self.assertEqual(m.set[1], (0, params, 1))


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


class PerKeyV1Test(unittest.TestCase):
	def test_apply_8080(self):
		kb = simulate.FakeKeyboardV1()
		dev = hidpp.Device(kb, reports={hidpp.LONG, hidpp.VERY_LONG})
		colors = {f'PERKEY_KEYBOARD:{k}': [k, 1, 2] for k in range(4, 34)}   # 30 keys: 3 requests of <= 14
		colors['PERKEY_BRANDING:1'] = [9, 9, 9]
		colors['PERKEY_GKEY:1'] = [7, 7, 7]          # the keyboard has no G-keys: left out
		self.assertEqual(perkey.apply(dev, colors), 31)
		self.assertEqual(kb.keys[(0x01, 4)], (4, 1, 2))
		self.assertEqual(kb.keys[(0x01, 33)], (33, 1, 2))
		self.assertEqual(kb.keys[(0x10, 1)], (9, 9, 9))
		self.assertNotIn((0x04, 1), kb.keys)
		self.assertTrue(kb.persisted)

	def test_long_reports_only(self):
		kb = simulate.FakeKeyboardV1()
		dev = hidpp.Device(kb, reports={hidpp.LONG})
		self.assertEqual(perkey.apply(dev, {f'PERKEY_KEYBOARD:{k}': [1, 2, 3] for k in range(4, 11)}), 7)
		self.assertEqual(len(kb.keys), 7)
