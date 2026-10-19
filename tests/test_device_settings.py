import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import device_settings  # noqa: E402
import hidpp  # noqa: E402
import simulate  # noqa: E402


class PowerTimersTest(unittest.TestCase):
	def test_read_and_write(self):
		fake = simulate.FakeWheelMouse()
		dev = hidpp.Device(fake)
		self.assertEqual(device_settings.power_timers(dev), {1: 300, 2: 600})
		device_settings.set_timeout(dev, device_settings.POWER_OFF, 30 * 60)
		self.assertEqual(device_settings.timeout(dev, device_settings.POWER_OFF), 1800)
		self.assertFalse(fake.session)                     # every session ended

	def test_long_tag_in_fragments(self):
		fake = simulate.FakeWheelMouse()
		dev = hidpp.Device(fake)
		data = bytes(range(40))
		device_settings.write_tag(dev, 16, data)
		self.assertEqual(fake.tags[16], data)
		self.assertEqual(device_settings.read_tag(dev, 16), data)


if __name__ == '__main__':
	unittest.main()
