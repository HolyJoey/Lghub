"""The PRO equalizer on the G Pro X's own Conexant chip (CX2089x).

G HUB sets it through logi_audio_conexant.dll (class CxAudioHidDev2089x, chip table entry 5,
"ANDRUS"). Its HID transport (FUN_180006150) for memory space 1 (read / write, 0x0000-0x27FF,
up to 32 bytes per report, protocol variant 1, no checksum):
  request  report 4: [4, flags, length, address high, address low], data after it for writes;
           flags 0x40 = write, 0x10 = address above 0xFFFF
  reply    report 5: [5, data...]
Writes send report 4 with the data after the header and get no reply (protocol flag 0x10 off).
Register 0x1152 low 2 bits = the active EQ profile (set_profile 0x18000ef70). Each profile has 5
bands of 11 bytes of filter coefficients at profile * 0x37 + 0xFE9 (band 1-5). G HUB's
set_band_gain (0x18000f550): the band's type / frequency / Q, the new gain (dB x 256, +-12 dB),
its filter design (FUN_180001000) -> 11 bytes written back, then "apply": bit 0 of register
0x1154 set (read-modify-write, FUN_1800129f0) and 200 ms. The design and its inverse
(FUN_1800011e0) are Logitech's own code, run by bin/proeq-design (bridge/proeq_design.c) from the
DLL in G HUB's core depot, fetched at first use.

`python3 proeq.py [USB port]` prints what the chip holds (it only reads).
"""
import cmath
import math
import os
import select
import struct
import subprocess
import sys
import time

import hotplug
import store

SYS_HIDRAW = '/sys/class/hidraw'
REQUEST, REPLY = 4, 5
MAX_CHUNK = 32
PROFILE_REGISTER = 0x1152
BANDS_BASE, PROFILE_SIZE, BAND_SIZE, BAND_COUNT = 0xFE9, 0x37, 11, 5
TIMEOUT = 1.0
WRITE = 0x40
APPLY_REGISTER = 0x1154
BUSY_READS = 5                                       # FUN_18000e180
MAX_GAIN_DB = 12.0
TYPES = {0: 'peaking', 1: 'low shelf', 2: 'high shelf', 3: 'low-pass', 4: 'high-pass'}   # FUN_1800013b0
MODELS = ('pro_71_gaming_headset',)                   # G HUB's hasOnboardProEq
DLL_PATH = 'LGHUB/logi_audio_conexant.dll'          # in G HUB's core depot
DLL_SHA256 = '3b985cda853e8d5e0f3ccedb31822485661b9612c7097c38f9606f9bf836b05d'   # the build the RVAs are for
DLL = os.path.join(store.DATA_DIR, 'apo', 'logi_audio_conexant.dll')
HELPER = os.path.join(store.DATA_DIR, 'bin', 'proeq-design')


def fetch_dll():
	"""G HUB's Conexant DLL from its core depot (first use), checked against the build we know."""
	import hashlib
	if os.path.exists(DLL):
		return DLL
	import depots
	url = depots.SERVER + depots.CORE_DEPOT
	data = depots._read(url, depots.files_cached(url)[DLL_PATH])
	if hashlib.sha256(data).hexdigest() != DLL_SHA256:
		raise OSError('G HUB ships another build of logi_audio_conexant.dll; its band maths may have moved')
	os.makedirs(os.path.dirname(DLL), exist_ok=True)
	tmp = DLL + '.tmp'
	with open(tmp, 'wb') as f:
		f.write(data)
	os.replace(tmp, DLL)
	return DLL


def _helper(*args):
	out = subprocess.run([HELPER, '--dll', fetch_dll(), *map(str, args)], capture_output=True, text=True,
	                     timeout=10, check=True).stdout.split()
	return out


def analyse(record):
	"""(type, frequency Hz, Q x 256, gain dB) of an 11-byte band record, by G HUB's FUN_1800011e0
	(Q x 256: FUN_180001340 turns it into a bandwidth, asinh(128 / q))."""
	kind, freq, q, gain, status = (int(x) for x in _helper('analyse', bytes(record).hex()))
	if status:
		raise ValueError(f'G HUB could not read this band (status {status})')
	return kind, freq, q, gain / 256


def design(kind, freq, q, gain_db):
	"""The 11-byte record for a band, by G HUB's FUN_180001000 (its checks included)."""
	gain = round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain_db)) * 256)
	record, status = _helper('design', kind, freq, q, gain)
	if int(status):
		raise ValueError(f'G HUB refuses this band (status 0x{int(status):x})')
	return bytes.fromhex(record)


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

	def write(self, address, data):
		"""data to memory space 1 from address, in chunks of up to 32 (no reply)."""
		for start in range(0, len(data), MAX_CHUNK):
			chunk, a = data[start:start + MAX_CHUNK], address + start
			header = bytes([REQUEST, WRITE | (0x10 if a > 0xFFFF else 0), len(chunk), a >> 8 & 0xFF, a & 0xFF])
			os.write(self.fd, (header + bytes(chunk)).ljust(self.request_len, b'\0'))

	def apply(self):
		"""G HUB's command 0x1154: bit 0 set, read-modify-write, then 200 ms."""
		value = self.read(APPLY_REGISTER, 1)[0]
		self.write(APPLY_REGISTER, bytes([value | 1]))
		time.sleep(0.2)

	def profile(self):
		return self.read(PROFILE_REGISTER, 1)[0] & 3

	def busy(self):
		"""G HUB's check before a write (FUN_18000e180): bit 0 of 0x1154 (the apply bit) read up to 5
		times, back to back; True while the chip is still applying the last change."""
		for _try in range(BUSY_READS):
			if not self.read(APPLY_REGISTER, 1)[0] & 1:
				return False
		return True

	def _ready(self):
		if self.busy():                              # G HUB gives up without writing, as here
			raise OSError('the headset is still applying the last equalizer change')

	def set_profile(self, profile):
		self._ready()
		value = self.read(PROFILE_REGISTER, 1)[0]
		self.write(PROFILE_REGISTER, bytes([value & 0xFC | profile & 3]))
		self.apply()

	def bands(self, profile):
		"""[(type, frequency, Q, gain dB)] of a profile's 5 bands, as G HUB reads them."""
		return [analyse(r) for r in self.band_records(profile)]

	def set_band_gain(self, profile, band, gain_db):
		"""band 1-5: its gain, keeping its type / frequency / Q (G HUB's set_band_gain)."""
		address = profile * PROFILE_SIZE + BANDS_BASE + (band - 1) * BAND_SIZE
		kind, freq, q, _gain = analyse(self.read(address, BAND_SIZE))
		self._ready()
		self.write(address, design(kind, freq, q, gain_db))
		self.apply()

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
		exact = os.path.exists(HELPER)
		for p in range(4):
			print(f'profile {p}:')
			for i, r in enumerate(chip.band_records(p)):
				if exact:
					kind, freq, q, db = analyse(r)
					print(f'  band {i + 1}: {r.hex(" ")}  {TYPES.get(kind, kind)} {freq} Hz Q {q / 256:.2f} {db:+.2f} dB')
				else:
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
