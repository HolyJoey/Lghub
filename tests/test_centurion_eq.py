"""The newer headsets' onboard equalizer (centurion_eq.py): G HUB's request format and its filter
designer (run natively from its agent when the agent is here)."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import centurion_eq  # noqa: E402
import hidpp  # noqa: E402
from tests.test_centurion import PRO_X2, device  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..')
AGENT = os.path.join(ROOT, 're', 'ghub', 'lghub_agent.exe')
BANDS = [(100, 2, 7), (300, 2, 7), (1000, 0, 7), (3000, 4, 7), (8000, 1, 7)]


class Dev:
	def __init__(self):
		self.calls = []

	def call(self, feature, fn, params=b''):
		self.calls.append((feature, fn, bytes(params)))
		if fn == 0:
			return bytes([0, 0x18, 0, 0, 5]).ljust(16, b'\0')
		if fn == 1:
			body = b''.join(bytes([f >> 8, f & 0xFF, g & 0xFF, q]) for f, g, q in BANDS)
			return (bytes([0x80, 5]) + body).ljust(32, b'\0')
		return bytes(16)


class CenturionEqTest(unittest.TestCase):
	def test_read(self):
		self.assertEqual(centurion_eq.read(Dev()), BANDS)

	def test_set_gains_as_g_hub(self):
		dev = Dev()
		with mock.patch.object(centurion_eq, 'coefficients', return_value=b'\x05\x5a\x00\x00') as c:
			centurion_eq.set_gains(dev, [0, -3, 3, 20, 1], save=True)
		self.assertEqual(c.call_args[0][0], 0x18)
		_f, fn, params = dev.calls[-1]
		self.assertEqual(fn, 2)
		self.assertEqual(params[:2], bytes([0x80, 5]))                       # save: slot 0x80
		self.assertEqual(params[2:6], bytes([0, 100, 0, 7]))
		self.assertEqual(params[16], 12)                                      # 20 dB clamped (ours)
		self.assertEqual(dev.calls[1][2], b'\x00')                            # read slot (save ^ 1) << 7
		with self.assertRaises(ValueError):
			centurion_eq.set_gains(dev, [0, 0])

	def test_long_message_goes_in_fragments(self):
		dev, fake = device(PRO_X2)
		dev.request(5, 2, bytes(range(200)))
		self.assertGreater(len(fake.sent), 3)
		self.assertTrue(all(len(p) <= 3 + PRO_X2[4] for p in fake.sent))

	def test_agent_download_gets_its_own_size_limit(self):
		import hashlib
		import depots
		data = b'agent'
		with tempfile.TemporaryDirectory() as tmp, \
		     mock.patch.object(centurion_eq, 'AGENT', os.path.join(tmp, 'apo', 'lghub_agent.exe')), \
		     mock.patch.object(centurion_eq, 'AGENT_SHA256', hashlib.sha256(data).hexdigest()), \
		     mock.patch.object(depots, 'files_cached', return_value={centurion_eq.AGENT_PATH: (0, 97271448)}), \
		     mock.patch.object(depots, '_read', return_value=data) as read:
			path = centurion_eq.fetch_agent()
			self.assertTrue(os.path.exists(path))
		self.assertGreater(read.call_args[0][2], 97271448)             # above the 8 MB picture limit

	@unittest.skipUnless(os.path.exists(AGENT), 'needs G HUB\'s agent (local only)')
	def test_g_hub_designer(self):
		with tempfile.TemporaryDirectory() as tmp:
			helper = os.path.join(tmp, 'centurion-eq')
			subprocess.run(['gcc', '-O2', '-o', helper, os.path.join(ROOT, 'bridge', 'centurion_eq.c'),
			                os.path.join(ROOT, 'bridge', 'peloader.c'), '-lm'], check=True)
			with mock.patch.object(centurion_eq, 'HELPER', helper), \
			     mock.patch.object(centurion_eq, 'fetch_agent', return_value=AGENT):
				block = centurion_eq.coefficients(0x18, BANDS)
		self.assertEqual(block[:2], b'\x05\x5a')
		self.assertEqual(int.from_bytes(block[2:4], 'little'), len(block) - 4)
		self.assertEqual(block[4:11], bytes([3, 0x0E, 0, 2, 0, 0, 0]))        # two rates
		self.assertEqual(block[11], 1)                                        # 44.1 kHz first
		count = int.from_bytes(block[13:15], 'little')
		self.assertEqual(block[15 + 2 * count], 2)                            # then 48 kHz


if __name__ == '__main__':
	unittest.main()
