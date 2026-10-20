"""Pairing a new device to a receiver (register 0xB2 lock) against the simulated receiver."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import devices  # noqa: E402
import hidpp  # noqa: E402
import pairing  # noqa: E402
import simulate  # noqa: E402


class Clock:
	def __init__(self):
		self.now = 0.0

	def __call__(self):
		self.now += 1.0
		return self.now


class PairingTest(unittest.TestCase):
	def receiver(self, pid):
		return devices.Device('usb:r1', f'046d:{pid}', devices.model_for(f'046d:{pid}'))

	def test_lock_requests(self):
		self.assertEqual(pairing.lock_request(pairing.LS2), bytes([0x10, 0xFF, 0x80, 0xB2, 7, 0, 0]))
		self.assertTrue(pairing.can_pair(self.receiver('c547')))
		self.assertFalse(pairing.can_pair(self.receiver('c548')))    # Bolt: not this way

	def test_pair_opens_waits_and_closes(self):
		fake = simulate.FakeReceiver()
		with mock.patch.object(devices, 'receiver_transport', return_value=(fake, {hidpp.LONG})):
			slot = pairing.pair(self.receiver('c547'), clock=Clock())
		self.assertEqual(slot, 2)
		self.assertEqual(fake.lock_actions, [pairing.LS2, pairing.CLOSE])     # LS2 open, then closed

	def test_nothing_pairs_before_the_lock_closes(self):
		reports = [bytes([0x10, 0xFF, 0x4A, 1, 0, 0, 0]), None, bytes([0x10, 0xFF, 0x4A, 0, 0, 0, 0])]
		transport = mock.Mock()
		transport.read.side_effect = lambda _t: reports.pop(0) if reports else None
		self.assertIsNone(pairing.wait_for_pairing(transport, 100.0, Clock()))
		transport.read.side_effect = lambda _t: None
		self.assertIsNone(pairing.wait_for_pairing(transport, 3.0, Clock()))  # timed out


if __name__ == '__main__':
	unittest.main()
