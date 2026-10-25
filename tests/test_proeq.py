"""The PRO equalizer's read-only transport (G HUB's CxAudioHidDev2089x memory reads)."""
import math
import os
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import proeq  # noqa: E402

# Vendor page, report 4 out (63 bytes), report 5 in (63 bytes)
DESCRIPTOR = bytes([0x06, 0x00, 0xFF, 0x09, 0x01, 0xA1, 0x01,
                    0x85, 0x04, 0x75, 0x08, 0x95, 0x3F, 0x09, 0x01, 0x91, 0x02,
                    0x85, 0x05, 0x75, 0x08, 0x95, 0x3F, 0x09, 0x01, 0x81, 0x02, 0xC0])


class FakeChip:
	"""Memory space 1 as the chip answers it: report 5 = [5, data...]."""

	def __init__(self, memory):
		self.memory = memory
		self.sent = []
		self.replies = []

	def write(self, _fd, data):
		self.sent.append(bytes(data))
		n, a = data[2], data[3] << 8 | data[4]
		if data[1] & 0x40:                              # a write: no reply
			for i in range(n):
				self.memory[a + i] = data[5 + i]
		else:
			self.replies.append(bytes([5]) + bytes(self.memory.get(a + i, 0) for i in range(n)))
		return len(data)

	def read(self, _fd, _n):
		return self.replies.pop(0)


class ProEqTest(unittest.TestCase):
	def test_coefficients(self):
		# a flat band: b0 = 1 (0x4000 with shift byte 3 -> 2^-14), the rest 0
		flat = struct.pack('<5h', 0x4000, 0, 0, 0, 0) + bytes([3])
		self.assertEqual(proeq.coefficients(flat), (1.0, 0.0, 0.0, 0.0, 0.0))
		self.assertAlmostEqual(proeq.band_summary(proeq.coefficients(flat))[1], 0.0)
		# a +6 dB peak at 1 kHz (RBJ peaking, Q 1.41) comes back near 1 kHz, +6 dB
		a, w = 10 ** (6 / 40), 2 * math.pi * 1000 / 48000
		alpha = math.sin(w) / (2 * 1.41)
		b = [1 + alpha * a, -2 * math.cos(w), 1 - alpha * a]
		den = [1 + alpha / a, -2 * math.cos(w), 1 - alpha / a]
		coeffs = [x / den[0] for x in b] + [den[1] / den[0], den[2] / den[0]]
		words = [round(c * (1 << 14)) for c in coeffs[:3]] + [round(-c * (1 << 14)) for c in coeffs[3:]]
		freq, db = proeq.band_summary(proeq.coefficients(struct.pack('<5h', *words) + bytes([3])))
		self.assertAlmostEqual(db, 6.0, delta=0.1)
		self.assertAlmostEqual(freq, 1000, delta=50)

	def test_report_sizes(self):
		inputs, outputs = proeq.report_sizes(DESCRIPTOR)
		self.assertEqual((inputs, outputs), ({5: 64}, {4: 64}))

	def test_reads_in_chunks_of_32(self):
		memory = {0x1152: 0x06}
		memory.update({0xFE9 + 2 * 0x37 + i: i for i in range(0x37)})
		fake = FakeChip(memory)
		with mock.patch.object(proeq.os, 'open', return_value=7), \
		     mock.patch.object(proeq.os, 'write', side_effect=fake.write), \
		     mock.patch.object(proeq.os, 'read', side_effect=fake.read), \
		     mock.patch.object(proeq.select, 'select', return_value=([7], [], [])):
			chip = proeq.Chip('/dev/null', 64, 64)
			self.assertEqual(chip.profile(), 2)
			self.assertEqual(fake.sent[0][:5], bytes([4, 0, 1, 0x11, 0x52]))
			self.assertEqual(len(fake.sent[0]), 64)
			records = chip.band_records(2)
		self.assertEqual([len(r) for r in records], [11] * 5)
		self.assertEqual(records[1][0], 11)
		start = 0xFE9 + 2 * 0x37
		self.assertEqual([s[2:5] for s in fake.sent[1:]],
		                 [bytes([32, start >> 8, start & 0xFF]), bytes([23, (start + 32) >> 8, (start + 32) & 0xFF])])

	def _chip(self, memory):
		fake = FakeChip(memory)
		patches = [mock.patch.object(proeq.os, 'open', return_value=7),
		           mock.patch.object(proeq.os, 'write', side_effect=fake.write),
		           mock.patch.object(proeq.os, 'read', side_effect=fake.read),
		           mock.patch.object(proeq.select, 'select', return_value=([7], [], [])),
		           mock.patch.object(proeq.time, 'sleep')]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		return fake, proeq.Chip('/dev/null', 64, 64)

	def test_set_band_gain_as_g_hub(self):
		fake, chip = self._chip({0x1154: 0x80})
		designs = []

		def helper(*args):
			if args[0] == 'analyse':
				return ['0', '1000', '362', '0', '0']
			designs.append(args)
			return ['00112233445566778899aa', '0']
		with mock.patch.object(proeq, '_helper', side_effect=helper):
			chip.set_band_gain(1, 3, 6.0)
		self.assertEqual(designs, [('design', 0, 1000, 362, 1536)])
		start = 1 * 0x37 + 0xFE9 + 2 * 11
		self.assertEqual(bytes(fake.memory[start + i] for i in range(11)), bytes.fromhex('00112233445566778899aa'))
		self.assertEqual(fake.memory[0x1154], 0x81)                      # applied: bit 0 set, the rest kept

	def test_set_profile_keeps_the_other_bits(self):
		fake, chip = self._chip({0x1152: 0xF1, 0x1154: 0})
		chip.set_profile(2)
		self.assertEqual(fake.memory[0x1152], 0xF2)

	def test_busy_chip_is_not_written(self):
		fake, chip = self._chip({0x1152: 0xF1, 0x1154: 0x01})               # still applying
		with self.assertRaises(OSError):
			chip.set_profile(2)
		self.assertEqual(fake.memory[0x1152], 0xF1)

	def test_gain_is_clamped(self):
		with mock.patch.object(proeq, '_helper', return_value=['00' * 11, '0']) as h:
			proeq.design(0, 1000, 362, 40)
		self.assertEqual(h.call_args[0][-1], 12 * 256)

	@unittest.skipUnless(os.path.exists(os.path.join(os.path.dirname(__file__), '..', 're', 'conexant',
	                                                 'logi_audio_conexant.dll')), 'needs G HUB\'s DLL (local only)')
	def test_g_hub_design_round_trip(self):
		import subprocess
		import tempfile
		root = os.path.join(os.path.dirname(__file__), '..')
		with tempfile.TemporaryDirectory() as tmp:
			helper = os.path.join(tmp, 'proeq-design')
			subprocess.run(['gcc', '-O2', '-o', helper, os.path.join(root, 'bridge', 'proeq_design.c'),
			                os.path.join(root, 'bridge', 'peloader.c'), '-lm'], check=True)
			dll = os.path.join(root, 're', 'conexant', 'logi_audio_conexant.dll')
			with mock.patch.object(proeq, 'HELPER', helper), mock.patch.object(proeq, 'fetch_dll', return_value=dll):
				record = proeq.design(0, 1000, 362, 6.0)
				self.assertEqual(proeq.analyse(record)[:2], (0, 999))
				freq, db = proeq.band_summary(proeq.coefficients(record))
		self.assertAlmostEqual(db, 6.0, delta=0.05)
		self.assertAlmostEqual(freq, 1000, delta=20)

