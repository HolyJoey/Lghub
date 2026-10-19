import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import battery_model  # noqa: E402

# Shaped like G HUB's battery.xml (made-up numbers)
XML = '''<?xml version="1.0"?>
<powermodel vid="0x46d" pid="0x0aaa"><battery>
<discharge format="default"><![CDATA[
0,4.1,0
10,3.9,250
20,3.7,500
30,3.5,1000
]]></discharge>
<charging format="charging_topping"><ascending><![CDATA[
3.5,0
3.8,40
4.1,90
]]></ascending><descending><![CDATA[
4.05,100
]]></descending></charging>
</battery></powermodel>'''


class BatteryModelTest(unittest.TestCase):
	def test_percent(self):
		with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False) as f:
			f.write(XML)
		try:
			model = battery_model.parse(f.name)
		finally:
			os.unlink(f.name)
		self.assertEqual(battery_model.percent(model, 4.2), 100)
		self.assertEqual(battery_model.percent(model, 3.8), 50)     # 500 of 1000 used
		self.assertEqual(battery_model.percent(model, 3.4), 0)
		self.assertEqual(battery_model.percent(model, 3.9, charging=True), 40)
		self.assertEqual(battery_model.percent(model, 4.06, charging=True), 40)   # falling part left out

	def test_not_a_battery_file(self):
		with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False) as f:
			f.write('<x/>')
		try:
			self.assertIsNone(battery_model.parse(f.name))
		finally:
			os.unlink(f.name)


if __name__ == '__main__':
	unittest.main()
