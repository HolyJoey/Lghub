import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hidpp  # noqa: E402
import osd  # noqa: E402
import simulate  # noqa: E402
import store  # noqa: E402


class OsdTest(unittest.TestCase):
	def test_profile_and_dpi_notices(self):
		sent = []
		fake = simulate.FakeMouse()
		with tempfile.TemporaryDirectory() as d, mock.patch.object(store, 'CONFIG_DIR', d), \
				mock.patch.object(store, 'CONFIG_FILE', os.path.join(d, 'config.json')):
			f = osd.Follower(hidpp.Device(fake), 'G502 HERO', send=lambda t, b, r: sent.append((t, b, r)) or 7)
			f.handle(osd.PROFILE_ACTIVATED)
			f.handle(osd.DPI_CHANGED)
		self.assertEqual(sent[0], ('Profile 1', 'G502 HERO', 0))
		self.assertEqual(sent[1], ('800 DPI', 'G502 HERO', 7))      # replaces the first notice

	def test_report_rate_notice(self):
		sent = []
		with tempfile.TemporaryDirectory() as d, mock.patch.object(store, 'CONFIG_DIR', d), \
				mock.patch.object(store, 'CONFIG_FILE', os.path.join(d, 'config.json')):
			f = osd.Follower(hidpp.Device(simulate.FakeWheelMouse()), 'G502 X', send=lambda t, b, r: sent.append(t) or 1)
			f.handle(osd.RATE_CHANGED, 3)
			f.handle(osd.RATE_CHANGED, 6)
		self.assertEqual(sent, ['1 kHz', '8 kHz'])


if __name__ == '__main__':
	unittest.main()
