"""G HUB's sensitivity presets (MOUSE_SETTINGS_ADVANCED in defaults_override.json)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import dpi_presets  # noqa: E402


def preset(name, entries, default=3, shift=1, asymmetric=False):
	return {'name': name, 'attribute': 'MOUSE_SETTINGS_ADVANCED', 'mouseSettings': {
		'reportRate': {'value': 500, 'wirelessRate': 1000},
		'advancedDpiTable': {'defaultIndex': default, 'shiftIndex': shift, 'entries': {
			str(i + 1): {'dpi': dpi, 'disabled': dpi is None, 'asymmetric': asymmetric} for i, dpi in enumerate(entries)}}}}


DATA = {'presets': [
	{'attribute': 'MOUSE_SENSITIVITY', 'name': 'TR_DEFAULT_MOUSE_SENSITIVITY'},
	preset('MSA_PREFAB_FIRST_PERSON', [400, 800, 1600, None, None], default=2),
	preset('MSA_PREFAB_FIRST_PERSON_XY', [400, 600, 800, None, None], asymmetric=True),
	preset('MSA_PREFAB_00_DEFAULT', [800, 1200, 1600, 2400, 3200]),
	preset('MSA_PREFAB_PRO_M0NESY', [400, None, None, None, None], default=4)]}


class DpiPresetsTest(unittest.TestCase):
	def test_parse(self):
		found = dpi_presets.parse(DATA)
		self.assertEqual([p.name for p in found], ['Default Settings', 'First Person', 'M0NESY'])
		default, first, pro = found
		self.assertEqual((default.levels, default.default, default.shift, default.rate),
		                 ([800, 1200, 1600, 2400, 3200], 2, 0, 500))
		self.assertEqual((first.levels, first.default), ([400, 800, 1600, 0, 0], 1))
		self.assertEqual(pro.default, 0)          # level 4 is off: the first level instead


if __name__ == '__main__':
	unittest.main()
