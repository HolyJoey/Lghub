"""The newer headsets' onboard equalizer (HID++ feature 0x0636 over the Centurion transport), as G HUB
sets it (re/notes/centurion.txt):

- fn 0 info: byte 1 = the sample rates the headset filters at (bit n = RATES[n]), byte 4 = the most
  bands it takes (G HUB refuses more gains than that).
- fn 1 read [slot]: [flag (bit 7 of byte 0), n, n x (frequency u16 BE, gain dB i8, q)].
- fn 2 write [slot, n, n x (frequency u16 BE, gain, q), coefficient block].
- Slots: G HUB reads (save ^ 1) << 7 and writes save << 7 (FeatureC0636OnboardEq 0x142232370).
- The coefficient block comes from the filter designer inside G HUB's agent, run natively by
  bin/centurion-eq (bridge/centurion_eq.c) from the agent in G HUB's core depot, fetched at first
  use and checked against the build its RVAs are for."""
import hashlib
import os
import subprocess

import store

EQ = 0x0636
INFO, READ, WRITE = 0, 1, 2
RATES = (0, 96000, 88200, 48000, 44100, 24000, 16000, 8000)
GAIN_RANGE = (-12, 12)                     # ours: G HUB's dB range for these isn't read yet
AGENT_PATH = 'LGHUB/lghub_agent.exe'      # in G HUB's core depot
AGENT_SHA256 = '1fe8d2e0da5acea8829eb96fcf65e8b7efa4f03a5eff53ffae15469de6c9a22b'
AGENT_MAX_BYTES, AGENT_TIMEOUT = 128 << 20, 600     # one large file (about 93 MB): its own limits
AGENT = os.path.join(store.DATA_DIR, 'apo', 'lghub_agent.exe')
HELPER = os.path.join(store.DATA_DIR, 'bin', 'centurion-eq')


def fetch_agent():
	"""G HUB's agent from its core depot (first use, about 93 MB), checked against the known build."""
	if os.path.exists(AGENT):
		return AGENT
	import depots
	url = depots.SERVER + depots.CORE_DEPOT
	data = depots._read(url, depots.files_cached(url)[AGENT_PATH], AGENT_MAX_BYTES, AGENT_TIMEOUT)
	if hashlib.sha256(data).hexdigest() != AGENT_SHA256:
		raise OSError('G HUB ships another build of its agent; the equalizer maths may have moved')
	os.makedirs(os.path.dirname(AGENT), exist_ok=True)
	tmp = AGENT + '.tmp'
	with open(tmp, 'wb') as f:
		f.write(data)
	os.replace(tmp, AGENT)
	return AGENT


def info(dev):
	"""(rate mask, most bands)."""
	r = dev.call(EQ, INFO)
	return r[1], r[4]


def read(dev, save=False):
	"""[(frequency Hz, gain dB, q)] of the bands in the slot G HUB reads."""
	r = dev.call(EQ, READ, bytes([(int(save) ^ 1) << 7]))
	n = r[1]
	out = []
	for i in range(n):
		at = 2 + 4 * i
		if at + 4 > len(r):
			break
		gain = r[at + 2] - 256 if r[at + 2] > 127 else r[at + 2]
		out.append(((r[at] << 8) | r[at + 1], gain, r[at + 3]))
	return out


def coefficients(mask, bands):
	"""The coefficient block for these bands (G HUB's designer, via bin/centurion-eq)."""
	args = [f'{f}:{g}:{q}' for f, g, q in bands]
	out = subprocess.run([HELPER, '--exe', fetch_agent(), str(mask), *args], capture_output=True, text=True,
	                     timeout=30, check=True).stdout.strip()
	return bytes.fromhex(out)


def set_gains(dev, gains, save=False):
	"""New gains (dB) for the headset's bands, keeping their frequencies and q (G HUB's request
	takes gains only; it checks their count against the headset's)."""
	mask, most = info(dev)
	bands = read(dev, save)
	if len(gains) != len(bands) or len(gains) > most:
		raise ValueError('gain count mismatch')
	low, high = GAIN_RANGE
	bands = [(f, max(low, min(high, int(round(g)))), q) for (f, _g, q), g in zip(bands, gains)]
	body = b''.join(bytes([f >> 8, f & 0xFF, g & 0xFF, q]) for f, g, q in bands)
	dev.call(EQ, WRITE, bytes([int(save) << 7, len(bands)]) + body + coefficients(mask, bands))
