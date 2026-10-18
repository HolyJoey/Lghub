"""Headset hardware controls: the mixer of the headset's own USB sound card (volume, mic level,
sidetone on most USB headsets) and, where the headset speaks HID++, its sidetone feature."""
import os
import re
import subprocess

SIDETONE = 0x8300     # HID++: function 0 get level (0-100), function 1 set level
SYS_SOUND = '/sys/class/sound'


def alsa_card(usb_port):
	"""ALSA card number of a USB device (port like '3-2'), or None."""
	try:
		names = os.listdir(SYS_SOUND)
	except OSError:
		return None
	for name in sorted(names):
		if not re.fullmatch(r'card\d+', name):
			continue
		real = os.path.realpath(os.path.join(SYS_SOUND, name, 'device'))
		if f'/{usb_port}:' in real or real.endswith(f'/{usb_port}'):
			return int(name[4:])
	return None


class Control:
	"""One ALSA simple mixer control, as amixer reports it."""

	def __init__(self, name, index):
		self.name = name
		self.index = index
		self.caps = set()
		self.low = self.high = 0
		self.values = []        # raw volume per channel
		self.on = None          # playback/capture switch
		self.db = None

	@property
	def id(self):
		return f"'{self.name}',{self.index}"

	@property
	def capture(self):
		return 'cvolume' in self.caps or 'cswitch' in self.caps and 'pvolume' not in self.caps

	@property
	def has_volume(self):
		return bool(self.caps & {'volume', 'pvolume', 'cvolume'}) and self.high > self.low

	@property
	def has_switch(self):
		return bool(self.caps & {'switch', 'pswitch', 'cswitch'})

	@property
	def percent(self):
		if not self.values or self.high <= self.low:
			return 0
		return round(100 * (sum(self.values) / len(self.values) - self.low) / (self.high - self.low))

	@property
	def is_sidetone(self):
		return 'sidetone' in self.name.lower()


def parse_scontents(text):
	controls, current = [], None
	for line in text.splitlines():
		m = re.match(r"Simple mixer control '(.*)',(\d+)", line)
		if m:
			current = Control(m[1], int(m[2]))
			controls.append(current)
			continue
		if current is None:
			continue
		line = line.strip()
		if line.startswith('Capabilities:'):
			current.caps = set(line.split(':', 1)[1].split()) - {'volume-joined', 'pswitch-joined', 'cswitch-joined'}
			if 'pvolume-joined' in line or 'cvolume-joined' in line:
				current.caps |= {'pvolume' if 'pvolume-joined' in line else 'cvolume'}
		elif line.startswith('Limits:'):
			nums = [int(n) for n in re.findall(r'-?\d+', line)]
			if len(nums) >= 2:
				current.low, current.high = nums[-2], nums[-1]
		elif ':' in line and (m := re.search(r'(?:Playback|Capture)?\s*(-?\d+)\s*\[\d+%\]', line)):
			current.values.append(int(m[1]))
			if (d := re.search(r'\[(-?[\d.]+)dB\]', line)):
				current.db = float(d[1])
			if (s := re.search(r'\[(on|off)\]', line)):
				current.on = s[1] == 'on'
		elif ':' in line and (s := re.search(r'\[(on|off)\]', line)):
			current.on = s[1] == 'on'
	return controls


def controls(card):
	try:
		out = subprocess.run(['amixer', '-c', str(card), 'scontents'], capture_output=True, text=True,
		                     timeout=5).stdout
	except (OSError, subprocess.TimeoutExpired):
		return []
	return [c for c in parse_scontents(out) if c.has_volume or c.has_switch]


def set_volume(card, control, percent):
	_amixer(card, control, f'{max(0, min(100, int(percent)))}%')


def set_switch(card, control, on):
	if control.capture:
		_amixer(card, control, 'cap' if on else 'nocap')
	else:
		_amixer(card, control, 'on' if on else 'off')


def _amixer(card, control, value):
	subprocess.run(['amixer', '-q', '-c', str(card), 'sset', control.id, value], capture_output=True, timeout=5)


# --- HID++ sidetone --------------------------------------------------------------------------

def sidetone(dev):
	return dev.call(SIDETONE, 0)[0]


def set_sidetone(dev, level):
	dev.call(SIDETONE, 1, bytes([max(0, min(100, int(level)))]))
