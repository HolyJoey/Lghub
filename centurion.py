"""G HUB's Centurion transport: how the newer Logitech headsets (G735, PRO X 2, G325, ...) carry HID++
over their own HID collection. From G HUB's agent (re/notes/centurion.txt):

- Which headsets and how: a built-in table (static init 0x1402111c0) per pid: the HID usage page /
  usage of the collection, a prefix, whether a length byte goes in, and the largest packet.
- CenturionPacketLayer (0x14200f3c0 write, 0x14200ed10 read): a message longer than one packet is
  split; each fragment repeats the message's first 2 bytes, then a byte seq << 1 | 1 (more to come)
  or seq << 1 (last), then the next (packet - 1) bytes. seq counts 0..127.
- CenturionTransport (0x14200d030 write, 0x14200cac0 read), below the packet layer: drops the
  device index, puts in the length byte (bytes after byte 0) and the prefix after byte 0; the read
  side undoes it and gives back [0x12, 0xFF, feature, function, ...].

So hidpp.Device runs on top of it unchanged. Ours: byte 0 on the wire is the collection's report id
(G HUB's HID layer isn't read; it passes byte 0 through)."""
import os
import time

import hidpp

SYS_HIDRAW = '/sys/class/hidraw'
HEADER = 2                       # the packet layer's header length (G HUB passes 2)

# pid: (usage page, usage, prefix, length byte, largest packet) - G HUB's entries that add a
# transport (a prefix or a length byte); the table's other entries add nothing for these pids
ENTRIES = {
	0x0AD8: (0xFF03, 1, bytes.fromhex('01051efa8240ce0000002000000000')[:14], False, 0x20),
	0x0AF7: (0xFFA0, 1, b'', True, 0x3D),
	**{pid: (0xFF32, 0x74, b'\x0c', True, 0x3D) for pid in (0x0B0B, 0x0B09, 0x0B1C, 0x0B1A)},
	**{pid: (0xFFA0, 1, b'\x23', True, 0x3D) for pid in (0x0A7B, 0x0B19, 0x0B18, 0x0B35, 0x0B2E, 0x0B21,
	                                                      0x0B3A, 0x0B47, 0x0B45, 0x0B40)},
}


def fragments(msg, packet):
	"""The packet layer's split of one HID++ message (bytes from the report id on)."""
	head, chunk = msg[:HEADER], packet - 1
	out, offset, seq = [], HEADER, 0
	while offset + chunk < len(msg):
		out.append(head + bytes([seq << 1 | 1]) + msg[offset:offset + chunk])
		seq, offset = (seq + 1) & 0x7F, offset + chunk
	out.append(head + bytes([seq << 1]) + msg[offset:])
	return out


def wrap(packet, prefix, length_byte):
	"""CenturionTransport's write: [rid, index, ...] -> [rid, prefix..., length?, ...]."""
	body = packet[2:]
	if length_byte:
		body = bytes([len(body)]) + body
	return packet[:1] + prefix + body


def unwrap(report, prefix, length_byte):
	"""CenturionTransport's read: back to [0x12, 0xFF, ...], or None when it is too short."""
	if len(report) < len(prefix) + length_byte + 1:
		return None
	body = report[1 + len(prefix):]
	if length_byte:
		body = body[1:1 + body[0]].ljust(body[0], b'\0')
	return bytes([hidpp.VERY_LONG, hidpp.CORDED]) + body


class Reassembler:
	"""The packet layer's read: fragments in, whole messages out."""

	def __init__(self):
		self.buffer, self.expect = b'', 0

	def feed(self, packet):
		if len(packet) < HEADER + 1:
			return None
		ctl = packet[HEADER]
		more, seq = ctl & 1, ctl >> 1
		if seq == 0:
			self.buffer, self.expect = packet[:HEADER], 0
		if seq != self.expect:                       # lost a fragment: wait for the next start
			self.expect = -1
			return None
		self.buffer += packet[HEADER + 1:]
		if more:
			self.expect = (seq + 1) & 0x7F
			return None
		self.expect = 0
		return self.buffer


class CenturionTransport:
	"""A hidpp transport over a Centurion collection (/dev/hidrawN)."""

	def __init__(self, path, entry, report_id):
		self.raw = hidpp.HidrawTransport(path)
		self.lock = self.raw.lock
		_page, _usage, self.prefix, self.length_byte, self.packet = entry
		self.report_id = report_id
		self.reader = Reassembler()

	def write(self, data):
		for frag in fragments(bytes(data), self.packet):
			self.raw.write(bytes([self.report_id]) + wrap(frag, self.prefix, self.length_byte)[1:])

	def read(self, timeout):
		deadline = time.monotonic() + timeout
		while (left := deadline - time.monotonic()) > 0:
			report = self.raw.read(left)
			if report is None:
				return None
			msg = unwrap(report, self.prefix, self.length_byte)
			whole = self.reader.feed(msg) if msg else None
			if whole:
				return whole
		return None

	def close(self):
		self.raw.close()


def _collection(desc):
	"""(first usage page, first usage, first report id or 0) of a HID report descriptor."""
	page = usage = rid = None
	i = 0
	while i < len(desc):
		prefix = desc[i]
		if prefix == 0xFE:
			i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
			continue
		size = (0, 1, 2, 4)[prefix & 3]
		data = int.from_bytes(desc[i + 1:i + 1 + size], 'little')
		tag = prefix & 0xFC
		if tag == 0x04 and page is None:
			page = data
		elif tag == 0x08 and usage is None:
			usage = data
		elif tag == 0x84 and rid is None:
			rid = data
		i += 1 + size
	return page, usage, rid or 0


def find(usb_port, pid):
	"""(hidraw path, report id) of the headset's Centurion collection, or None."""
	entry = ENTRIES.get(pid)
	if not entry:
		return None
	import hotplug
	try:
		names = sorted(os.listdir(SYS_HIDRAW))
	except OSError:
		return None
	for name in names:
		if not hotplug.on_port(os.path.realpath(os.path.join(SYS_HIDRAW, name, 'device')), usb_port):
			continue
		try:
			with open(os.path.join(SYS_HIDRAW, name, 'device', 'report_descriptor'), 'rb') as f:
				page, usage, rid = _collection(f.read())
		except OSError:
			continue
		if (page, usage) == entry[:2]:
			return f'/dev/{name}', rid
	return None


def open_usb(usb_port, pid):
	"""A hidpp.Device over the headset's Centurion transport, or raises OSError."""
	found = find(usb_port, pid)
	if not found:
		raise OSError('no Centurion collection')
	dev = hidpp.Device(CenturionTransport(found[0], ENTRIES[pid], found[1]), hidpp.CORDED, (hidpp.VERY_LONG,))
	try:
		dev.protocol_version()
	except hidpp.HidppError:
		dev.close()
		raise OSError('the Centurion collection did not answer') from None
	return dev

