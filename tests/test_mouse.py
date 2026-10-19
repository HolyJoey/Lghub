"""Mouse protocol tests against the simulated mouse: python3 -m unittest discover tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hidpp  # noqa: E402
import mouse  # noqa: E402
import simulate  # noqa: E402


class MouseTest(unittest.TestCase):
	def setUp(self):
		self.fake = simulate.FakeMouse()
		self.tmp = tempfile.TemporaryDirectory()
		mouse.BACKUP_DIR = self.tmp.name
		self.m = mouse.Mouse(hidpp.Device(self.fake), 'test')

	def tearDown(self):
		self.tmp.cleanup()

	def test_identity(self):
		self.assertEqual(self.m.name, 'G502 HERO Gaming Mouse')
		self.assertEqual(self.m.firmware, 'U1 12.02.B0007')
		self.assertIn(mouse.ONBOARD, self.m.features)

	def test_sensor_and_rates(self):
		self.assertEqual((self.m.sensor.low, self.m.sensor.high, self.m.sensor.step), (100, 25600, 50))
		self.assertEqual(self.m.sensor.clamp(1234), 1250)
		self.assertEqual(self.m.rates, [1000, 500, 250, 125])
		self.m.set_rate(500)
		self.assertEqual(self.m.current_rate(), 500)

	def test_unknown_feature_is_an_error(self):
		with self.assertRaises(hidpp.HidppError):
			self.m.dev.call(0x8070, 0)

	def test_factory_profiles(self):
		profiles = self.m.load_profiles()
		self.assertFalse(self.m.directory_valid)
		self.assertEqual(len(profiles), 3)
		p = profiles[0]
		self.assertEqual(p.name, 'Profile 1')
		self.assertEqual(p.dpi_levels, [400, 800, 1600, 3200, 6400])
		self.assertEqual(p.report_rate, 1000)
		self.assertEqual(p.button(0).describe(), 'Left click')
		self.assertEqual(p.button(7).describe(), 'DPI shift')
		self.assertEqual(p.led(1).effect, mouse.LED_BREATHING)
		self.assertEqual(p.led(1).period, 4000)
		self.assertEqual(p.led(1).brightness, 80)

	def test_save_copies_to_user_memory(self):
		profiles = self.m.load_profiles()
		p = profiles[1]
		p.set_dpi(2, 4000)
		p.name = 'Shooter'
		p.set_button(4, mouse.Action.key(0x01, 0x06))
		p.set_led(0, mouse.Led.build(mouse.LED_CYCLE, period=8000, brightness=50))
		self.m.save(profiles)
		self.assertTrue(self.m.directory_valid)
		self.assertTrue(mouse.crc_ok(self.fake.memory[0]))
		self.assertTrue(mouse.crc_ok(self.fake.memory[2]))
		again = mouse.Mouse(hidpp.Device(self.fake), 'test').load_profiles()
		self.assertEqual([q.sector for q in again], [1, 2, 3])
		self.assertEqual(again[1].name, 'Shooter')
		self.assertEqual(again[1].dpi_levels[:3], [1200, 2400, 4000])
		self.assertEqual(again[1].button(4).describe(), 'Ctrl + C')
		self.assertEqual((again[1].led(0).effect, again[1].led(0).period), (mouse.LED_CYCLE, 8000))
		self.assertFalse(any(q.dirty for q in again))
		self.assertTrue(os.path.exists(os.path.join(self.tmp.name, 'test', 'sector_0000.bin')))

	def test_dpi_list_with_explicit_values(self):
		sensor = mouse.parse_dpi_list([400, 800, 1600, 0])
		self.assertEqual(sensor.values, [400, 800, 1600])
		self.assertEqual(sensor.clamp(1000), 800)


class DescriptorTest(unittest.TestCase):
	def test_finds_hidpp_reports(self):
		# usage page 0xFF00, report id 0x10 ... report id 0x11
		desc = bytes([0x06, 0x00, 0xFF, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x10, 0xC0, 0x85, 0x11])
		ids, vendor = hidpp._descriptor_reports(desc)
		self.assertTrue(vendor)
		self.assertEqual(ids, {0x10, 0x11})


if __name__ == '__main__':
	unittest.main()


class WheelTest(unittest.TestCase):
	def test_smartshift(self):
		fake = simulate.FakeWheelMouse()
		m = mouse.Mouse(hidpp.Device(fake), 'test')
		self.assertEqual(m.wheel(), {'mode': mouse.RATCHET, 'auto': 10, 'torque': 50, 'max_torque': 100})
		m.set_wheel(mouse.RATCHET, mouse.ALWAYS_RATCHET, 30)
		self.assertEqual(fake.wheel, [2, 0xFF, 30])
		m.set_wheel(mouse.FREE_SPIN, 0, 30)
		self.assertEqual(fake.wheel[0], 1)
		self.assertIsNone(mouse.Mouse(hidpp.Device(simulate.FakeMouse()), 'g502').wheel())

	def test_extended_report_rate(self):
		fake = simulate.FakeWheelMouse()
		m = mouse.Mouse(hidpp.Device(fake), 'test')
		self.assertEqual(m.rates, [8000, 4000, 2000, 1000, 500, 250, 125])
		self.assertEqual(m.current_rate(), 1000)
		m.set_rate(8000)
		self.assertEqual(fake.rate_n, 6)
		self.assertEqual(m.current_rate(), 8000)

	def test_extended_dpi(self):
		fake = simulate.FakeWheelMouse()
		m = mouse.Mouse(hidpp.Device(fake), 'test')
		self.assertEqual((m.sensor.low, m.sensor.high, m.sensor.step), (100, 32000, 50))
		self.assertEqual(m.current_dpi(), 1600)
		m.set_dpi(3200)
		self.assertEqual(fake.ext_dpi, (3200, 3200, 2))     # Y follows X, lift-off kept

	def test_swap_and_hybrid(self):
		import features
		fake = simulate.FakeWheelMouse()
		dev = hidpp.Device(fake)
		self.assertFalse(features.button_swap(dev))
		features.set_button_swap(dev, True)
		self.assertEqual(fake.swap, 1)
		self.assertEqual(features.hybrid_mode(dev), 0)
		features.set_hybrid_mode(dev, 1)
		self.assertEqual(features.hybrid_mode(dev), 1)
