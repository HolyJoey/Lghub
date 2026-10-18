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


DB = re.compile(r'\[(-?[\d.]+)dB\]')
SWITCH = re.compile(r'\[(on|off)\]')
JOINED = {'pvolume-joined': 'pvolume', 'cvolume-joined': 'cvolume'}


def _capabilities(control, text):
	words = text.split()
	control.caps = {JOINED.get(w, w) for w in words if not w.endswith('switch-joined') and w != 'volume-joined'}


def _limits(control, text):
	nums = [int(n) for n in re.findall(r'-?\d+', text)]
	if len(nums) >= 2:
		control.low, control.high = nums[-2], nums[-1]


def _channel(control, text):
	"""A channel line, e.g. 'Front Left: Playback 56 [64%] [-23.25dB] [on]'."""
	words = text.split()
	for before, word in zip(words, words[1:]):
		if word.startswith('[') and word.endswith('%]') and before.lstrip('-').isdigit():
			control.values.append(int(before))
			if (d := DB.search(text)):
				control.db = float(d[1])
			break
	if (sw := SWITCH.search(text)):
		control.on = sw[1] == 'on'


def parse_scontents(text):
	controls, current = [], None
	for line in text.splitlines():
		m = re.match(r"Simple mixer control '(.*)',(\d+)", line)
		if m:
			current = Control(m[1], int(m[2]))
			controls.append(current)
			continue
		key, _, rest = line.strip().partition(':')
		if current is None or not rest:
			continue
		if key == 'Capabilities':
			_capabilities(current, rest)
		elif key == 'Limits':
			_limits(current, rest)
		elif not key.endswith('channels'):
			_channel(current, rest)
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
