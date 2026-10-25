"""G HUB's Centurion transport (centurion.py) and the 0x0604 sidetone over it (headset.py)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import centurion  # noqa: E402
import headset  # noqa: E402
import hidpp  # noqa: E402

PRO_X2 = centurion.ENTRIES[0x0AF7]
G325 = centurion.ENTRIES[0x0B21]


class FakeHeadset:
	"""A Centurion headset behind the transport: answers root (0x0604 at index 5, version 2) and
	0x0604 with one mic at level 20 of 41 steps."""

	def __init__(self, entry, report_id):
		self.entry, self.report_id = entry, report_id
		self.lock = None
		self.sent, self.queue, self.level = [], [], 20
		self.reader = centurion.Reassembler()

	def write(self, data):
		self.sent.append(bytes(data))
		_page, _usage, prefix, length_byte, packet = self.entry
		msg = self.reader.feed(centurion.unwrap(bytes(data), prefix, length_byte))
		if msg is None:
			return
		feature, func, params = msg[2], msg[3], msg[4:]
		if feature == 0:
			body = bytes([5, 0, 2]) if params[:2] == b'\x06\x04' else bytes([0, 0, 0])
		elif func >> 4 == 0:
			body = bytes([1, 0, 0xFF, self.level])
		elif func >> 4 == 1:
			self.level, body = params[2], b''
		else:
			body = bytes([0, 0, 41])
		reply = (bytes([0x11, 0xFF, feature, func]) + body).ljust(20, b"\0")
		for frag in centurion.fragments(reply, packet):
			self.queue.append(bytes([self.report_id]) + centurion.wrap(frag, prefix, length_byte)[1:])

	def read(self, _timeout):
		return self.queue.pop(0) if self.queue else None

	def close(self):
		pass


def device(entry, report_id=0x51):
	t = centurion.CenturionTransport.__new__(centurion.CenturionTransport)
	t.raw = FakeHeadset(entry, report_id)
	t.lock = __import__('threading').Lock()
	_page, _usage, t.prefix, t.length_byte, t.packet = entry
	t.report_id, t.reader = report_id, centurion.Reassembler()
	return hidpp.Device(t, hidpp.CORDED, (hidpp.VERY_LONG,)), t.raw


class CenturionTest(unittest.TestCase):
	def test_wire_format(self):
		msg = bytes([0x11, 0xFF, 0x05, 0x1A, 1, 2])
		frag = centurion.fragments(msg, 0x3D)
		self.assertEqual(frag, [bytes([0x11, 0xFF, 0, 0x05, 0x1A, 1, 2])])
		self.assertEqual(centurion.wrap(frag[0], b'\x23', True), bytes([0x11, 0x23, 5, 0, 0x05, 0x1A, 1, 2]))

	def test_fragments_and_reassembly(self):
		msg = bytes([0x12, 0xFF]) + bytes(range(150))
		frags = centurion.fragments(msg, 0x3D)
		self.assertEqual([f[2] for f in frags], [1, 3, 4])               # seq << 1 | more
		self.assertTrue(all(len(f) <= 0x3D + 2 for f in frags))
		r = centurion.Reassembler()
		out = [r.feed(f) for f in frags]
		self.assertEqual(out[:2], [None, None])
		self.assertEqual(out[2], msg)

	def test_lost_fragment_is_dropped(self):
		frags = centurion.fragments(bytes([0x12, 0xFF]) + bytes(150), 0x3D)
		r = centurion.Reassembler()
		self.assertIsNone(r.feed(frags[0]))
		self.assertIsNone(r.feed(frags[2]))                               # seq 2 without seq 1

	def test_unwrap_truncates_to_the_length(self):
		self.assertEqual(centurion.unwrap(bytes([0x51, 0x23, 3, 0, 5, 6, 9, 9]), b'\x23', True),
		                 bytes([0x12, 0xFF, 0, 5, 6]))

	def test_sidetone_over_the_transport(self):
		for entry in (PRO_X2, G325):
			dev, fake = device(entry)
			self.assertEqual(headset.sidetone(dev), 50)                   # 20 of 0..40
			headset.set_sidetone(dev, 75)
			self.assertEqual(fake.level, 30)
			self.assertTrue(all(p[0] == 0x51 for p in fake.sent))           # the collection's report id
			if entry[2]:
				self.assertTrue(all(p[1:1 + len(entry[2])] == entry[2] for p in fake.sent))

	def test_mic_mute_and_gain(self):
		calls = []

		class Dev:
			def call(self, feature, fn, params=b''):
				calls.append((feature, fn, bytes(params)))
				answers = {(0x0601, 0): b'\x01', (0x0611, 0): b'\x00\x40', (0x0611, 1): b'\x20'}
				return answers.get((feature, fn), b'').ljust(16, b'\0')
		dev = Dev()
		self.assertTrue(headset.centurion_mic_muted(dev))
		headset.set_centurion_mic_muted(dev, False)
		self.assertEqual(headset.centurion_mic_gain(dev), (0x20, 0, 0x40))
		headset.set_centurion_mic_gain(dev, 99)
		self.assertIn((0x0601, 1, b'\x00'), calls)
		self.assertEqual(calls[-1], (0x0611, 2, b'\x40'))                 # clamped to the headset's max

	def test_anc(self):
		calls = []

		class Dev:
			def call(self, feature, fn, params=b''):
				calls.append((feature, fn, bytes(params)))
				return {(0x0605, 0): b'\x02', (0x0605, 2): b'\x13\x01'}.get((feature, fn), b'').ljust(16, b'\0')
		dev = Dev()
		self.assertEqual(headset.ANC_MODES[headset.anc_mode(dev)], 'Transparency')
		self.assertEqual(headset.anc_button(dev), ([0, 1, 4], 1))
		headset.set_anc_button(dev, [1, 2], 0)
		self.assertEqual(calls[-1], (0x0605, 3, b'\x06\x00'))

	def test_descriptor_collection(self):
		desc = bytes([0x06, 0xA0, 0xFF, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x51, 0xC0])
		self.assertEqual(centurion._collection(desc), (0xFFA0, 1, 0x51))


if __name__ == '__main__':
	unittest.main()
