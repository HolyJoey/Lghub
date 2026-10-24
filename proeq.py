"""The PRO equalizer on the G Pro X's own Conexant chip (CX2089x), read-only for now.

G HUB sets it through logi_audio_conexant.dll (class CxAudioHidDev2089x, chip table entry 5,
"ANDRUS"). Its HID transport (FUN_180006150) for memory space 1 (read / write, 0x0000-0x27FF,
up to 32 bytes per report, protocol variant 1, no checksum):
  request  report 4: [4, flags, length, address high, address low], data after it for writes;
           flags 0x40 = write, 0x10 = address above 0xFFFF
  reply    report 5: [5, data...]
Register 0x1152 low 2 bits = the active EQ profile (set_profile 0x18000ef70; command 0x1154
applies). Each profile has 5 bands of 11 bytes of filter coefficients at profile * 0x37 + 0xFE9
(set_band_gain 0x18000f550, band 1-5); G HUB turns them into frequency / gain / Q with its
filter design (FUN_1800011e0), not ported yet.

Nothing here writes to the headset. `python3 proeq.py [USB port]` prints what the chip answers.
"""
import cmath
import math
import os
import select
import struct
import sys

import hotplug

SYS_HIDRAW = '/sys/class/hidraw'
REQUEST, REPLY = 4, 5
MAX_CHUNK = 32
PROFILE_REGISTER = 0x1152
BANDS_BASE, PROFILE_SIZE, BAND_SIZE, BAND_COUNT = 0xFE9, 0x37, 11, 5
TIMEOUT = 1.0


def coefficients(record):
	"""(b0, b1, b2, a1, a2) of an 11-byte band record, as G HUB reads them (FUN_1800017c0 via
	FUN_1800011e0): five signed 16-bit words b0, b1, b2, -a1, -a2 and a shift byte; each word is
	scaled by 2^-(15 - (shift - 2))."""
	words = struct.unpack('<5h', record[:10])
	shift = record[10] - 2 if record[10] >= 2 else 0
	scale = 1.0 / (1 << ((15 - shift) & 31))
	b0, b1, b2, na1, na2 = (w * scale for w in words)
	return b0, b1, b2, -na1, -na2


def response_db(coeffs, freq, rate=48000):
	b0, b1, b2, a1, a2 = coeffs
	z = cmath.exp(-2j * math.pi * freq / rate)
	h = (b0 + b1 * z + b2 * z * z) / (1 + a1 * z + a2 * z * z)
	return 20 * math.log10(max(abs(h), 1e-9))


def band_summary(coeffs, rate=48000):
	"""(frequency, dB) where a band boosts or cuts most, 20 Hz - 20 kHz (ours: G HUB fits the
	filter's type, frequency and Q with FUN_180002e00, not ported)."""
	freqs = [20 * 1000 ** (i / 299) for i in range(300)]
	return max(((f, response_db(coeffs, f, rate)) for f in freqs), key=lambda p: abs(p[1]))


class _Globals:
	"""A report descriptor's global items that report sizes need, with push / pop."""

	def __init__(self):
		self.rid = self.size = self.count = 0
		self.stack = []

	def item(self, tag, data):
		if tag == 0x84:
			self.rid = data
		elif tag == 0x74:
			self.size = data
		elif tag == 0x94:
			self.count = data
		elif tag == 0xA4:
			self.stack.append((self.rid, self.size, self.count))
		elif tag == 0xB4 and self.stack:
			self.rid, self.size, self.count = self.stack.pop()


def _items(desc):
	"""(tag, data) of a report descriptor's short items (long items skipped)."""
	i = 0
	while i < len(desc):
		prefix = desc[i]
		if prefix == 0xFE:
			i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
			continue
		n = (0, 1, 2, 4)[prefix & 3]
		yield prefix & 0xFC, int.from_bytes(desc[i + 1:i + 1 + n], 'little')
		i += 1 + n


def report_sizes(desc):
	"""({report id: input bytes}, {report id: output bytes}) from a HID report descriptor (sizes
	include the id byte)."""
	bits = ({}, {})
	g = _Globals()
	for tag, data in _items(desc):
		if tag in (0x80, 0x90):                  # input / output main item
			table = bits[0 if tag == 0x80 else 1]
			table[g.rid] = table.get(g.rid, 0) + g.size * g.count
		else:
			g.item(tag, data)
	return tuple({r: (b + 7) // 8 + (1 if r else 0) for r, b in t.items()} for t in bits)


def find(usb_port):
	"""(hidraw path, request length, reply length) of the chip's interface on a USB port, or None."""
	try:
		names = sorted(os.listdir(SYS_HIDRAW))
	except OSError:
		return None
	for name in names:
		real = os.path.realpath(os.path.join(SYS_HIDRAW, name, 'device'))
		if not hotplug.on_port(real, usb_port):
			continue
		try:
			with open(os.path.join(SYS_HIDRAW, name, 'device', 'report_descriptor'), 'rb') as f:
				inputs, outputs = report_sizes(f.read())
		except OSError:
			continue
		if REQUEST in outputs and REPLY in inputs:
			return f'/dev/{name}', outputs[REQUEST], inputs[REPLY]
	return None


class Chip:
	def __init__(self, path, request_len, reply_len):
		self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
		self.request_len, self.reply_len = request_len, reply_len

	def close(self):
		os.close(self.fd)

	def _reply(self):
		end = TIMEOUT
		while end > 0:
			ready, _, _ = select.select([self.fd], [], [], end)
			if not ready:
				break
			data = os.read(self.fd, max(64, self.reply_len))
			if data and data[0] == REPLY:
				return data
			end -= 0.05
		raise TimeoutError('the chip did not answer')

	def read(self, address, length):
		"""length bytes of memory space 1 from address, in chunks of up to 32."""
		out = b''
		while len(out) < length:
			n = min(MAX_CHUNK, length - len(out))
			a = address + len(out)
			header = bytes([REQUEST, 0x10 if a > 0xFFFF else 0, n, a >> 8 & 0xFF, a & 0xFF])
			os.write(self.fd, header.ljust(self.request_len, b'\0'))
			out += self._reply()[1:1 + n]
		return out

	def profile(self):
		return self.read(PROFILE_REGISTER, 1)[0] & 3

	def band_records(self, profile):
		"""The 5 bands' 11-byte coefficient records of a profile."""
		data = self.read(profile * PROFILE_SIZE + BANDS_BASE, PROFILE_SIZE)
		return [data[i * BAND_SIZE:(i + 1) * BAND_SIZE] for i in range(BAND_COUNT)]


def _headset_port():
	import devices
	return next((d.port for d in devices.discover() if d.model.key == 'pro_71_gaming_headset'), None)


def main(argv):
	port = argv[1] if len(argv) > 1 else _headset_port()
	if not port:
		print('No wired G Pro X found (give its USB port, like 3-2).')
		return 1
	found = find(port)
	if not found:
		print(f'No HID interface with reports 4 / 5 on USB port {port}.')
		return 1
	path, request_len, reply_len = found
	print(f'{path}: request {request_len} bytes, reply {reply_len} bytes')
	chip = Chip(path, request_len, reply_len)
	try:
		profile = chip.profile()
		print(f'active profile {profile}')
		for p in range(4):
			print(f'profile {p}:')
			for i, r in enumerate(chip.band_records(p)):
				freq, db = band_summary(coefficients(r))
				print(f'  band {i + 1}: {r.hex(" ")}  ~{freq:.0f} Hz {db:+.1f} dB')
	except OSError as e:          # TimeoutError too
		print(f'failed: {e}')
		return 1
	finally:
		chip.close()
	return 0


if __name__ == '__main__':
	sys.exit(main(sys.argv))
