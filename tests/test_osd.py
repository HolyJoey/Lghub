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

	def test_events_become_notices(self):
		fake = hidpp.Device(simulate.FakeWheelMouse())
		f = osd.Follower(fake, 'G502 X', send=lambda *_a: 0)
		onboard, rates = fake.feature_index(osd.mouse.ONBOARD), fake.feature_index(osd.mouse.EXTENDED_RATE)
		events = [None, (onboard, osd.PROFILE_ACTIVATED, b''), (rates, 0, bytes([1, 3])), (onboard, 9, b'')]
		handled = []

		def next_event(_timeout):
			if not events:
				raise OSError('unplugged')
			return events.pop(0)

		with mock.patch.object(fake, 'next_event', next_event), mock.patch.object(fake, 'close') as close, \
				mock.patch.object(f, 'handle', lambda *a: handled.append(a)):
			f._run()
		self.assertEqual(handled, [(osd.PROFILE_ACTIVATED,), (osd.RATE_CHANGED, 3)])
		close.assert_called_once()

	def test_notices_off(self):
		sent = []
		f = osd.Follower(hidpp.Device(simulate.FakeWheelMouse()), 'G502 X', send=lambda *a: sent.append(a))
		with mock.patch('store.load_config', return_value={'osd_notifications': False}):
			f.handle(osd.RATE_CHANGED, 3)
		self.assertEqual(sent, [])

	def test_watch_follows_onboard_mice_only(self):
		mouse_dev = mock.Mock(id='m', model=mock.Mock(type='mouse'))
		mouse_dev.name = 'G502'
		keyboard = mock.Mock(id='k', model=mock.Mock(type='keyboard'))
		plain = mock.Mock(id='p', model=mock.Mock(type='mouse'))
		devices = mock.Mock()
		devices.discover.return_value = [mouse_dev, keyboard, plain]
		onboard, without = mock.Mock(), mock.Mock()
		onboard.has.return_value, without.has.return_value = True, False
		devices.open_hidpp.side_effect = lambda d: onboard if d is mouse_dev else without
		w = osd.Watch()
		with mock.patch.dict(sys.modules, {'devices': devices}), mock.patch.object(osd, 'Follower') as follower:
			w.check(5.0)
			w.check(6.0)
		self.assertEqual(list(w.followers), ['m'])
		follower.return_value.start.assert_called_once()
		self.assertEqual(without.close.call_count, 2)      # looked at again on each check
		self.assertTrue(w.due(6.0 + osd.Watch.CHECK_EVERY))
		w.stop()
		follower.return_value.stop.assert_called_once()


if __name__ == '__main__':
	unittest.main()
