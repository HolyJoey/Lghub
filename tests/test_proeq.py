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
