"""G HUB's battery "time left" from a power model (battery.xml <powermodel>): the parts' draw in
milliwatts for the report rate and lighting, hours = percent / 100 * Wh * 1000 / mW."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import battery_model  # noqa: E402

MODEL = '''<?xml version="1.0" encoding="utf-8"?>
<powermodel vid="0x46d" pid="0x4099">
  <battery><capacity watts_per_hour="2.0"/></battery>
  <blocks default_unit="milliwatts" nominal_voltage="3.8">
    <sensor model="hero2" power="2.0"><report_rate hertz="8000" power="10.0" /></sensor>
    <mcu model="x" power="3.0" />
    <report_rate>
      <interval milliseconds="0.125" power="30.0" />
      <interval milliseconds="1" power="5.0" />
    </report_rate>
    <lighting>
      <zone location="primary">
        <effect type="off" power="0.00" mcu_load="1.0" />
        <effect type="solid"><brightness percent="100" power="30.0"/><brightness percent="50" power="15.0"/></effect>
      </zone>
    </lighting>
  </blocks>
</powermodel>
'''


class BatteryLifeTest(unittest.TestCase):
	def setUp(self):
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		path = os.path.join(tmp.name, 'battery.xml')
		with open(path, 'w') as f:
			f.write(MODEL)
		self.model = battery_model.parse_power(path)

	def test_draw(self):
		self.assertEqual(battery_model.milliwatts(self.model, 1000, lit=False), 2 + 3 + 5 + 1)
		self.assertEqual(battery_model.milliwatts(self.model, 1000, lit=True), 2 + 3 + 5 + 30)
		self.assertEqual(battery_model.milliwatts(self.model, 8000, lit=False), 10 + 3 + 30 + 1)

	def test_hours(self):
		off, on = battery_model.hours_left(self.model, 50, 1000)
		self.assertAlmostEqual(off, 0.5 * 2000 / 11)
		self.assertAlmostEqual(on, 0.5 * 2000 / 40)
		self.assertEqual(battery_model.life_text(self.model, 50, 1000), 'about 25–91 h left')
		self.assertEqual(battery_model.life_text(self.model, 50, 1000, charging=True), '')

	def test_voltage_curves_are_not_power_models(self):
		self.assertIsNone(battery_model.parse_power(os.devnull))


if __name__ == '__main__':
	unittest.main()
