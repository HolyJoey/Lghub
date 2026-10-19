import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import receiver_watch  # noqa: E402


class FakeTransport:
	def __init__(self, reports, watch):
		self.reports, self.watch, self.closed = list(reports), watch, False

	def read(self, _timeout):
		if not self.reports:
			self.watch.stop()
			return None
		return self.reports.pop(0)

	def close(self):
		self.closed = True


class ReceiverWatchTest(unittest.TestCase):
	def test_connection_reports(self):
		self.assertEqual(receiver_watch.connected(bytes([0x10, 2, 0x41, 0x04, 0x01, 0x8b, 0xc0])), 2)
		self.assertIsNone(receiver_watch.connected(bytes([0x10, 2, 0x41, 0x04, 0x41, 0x8b, 0xc0])))   # link down
		self.assertIsNone(receiver_watch.connected(bytes([0x11, 0xff, 0x05, 0x10, 0])))           # other report

	def test_listen_sets_changed_once(self):
		watch = receiver_watch.Watch()
		t = FakeTransport([bytes([0x10, 1, 0x41, 0x04, 0x01, 0, 0])], watch)
		watch._listen(t)
		self.assertTrue(t.closed)
		self.assertTrue(watch.changed())
		self.assertFalse(watch.changed())


if __name__ == '__main__':
	unittest.main()
