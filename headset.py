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
	if not dev.has(SIDETONE) and dev.has(CENTURION_SIDETONE):
		return centurion_sidetone(dev)
	return dev.call(SIDETONE, 0)[0]


def set_sidetone(dev, level):
	if not dev.has(SIDETONE) and dev.has(CENTURION_SIDETONE):
		set_centurion_sidetone(dev, level)
		return
	dev.call(SIDETONE, 1, bytes([max(0, min(100, int(level)))]))


# 0x0601 HeadsetMicMute (Centurion): fn 0 get (byte 0 bit 0 = muted, decoder 0x141cb9b40), fn 1 set
# [muted]; fn 2 / 3 are the mic LED support pair (not used).
CENTURION_MIC_MUTE = 0x0601


def centurion_mic_muted(dev):
	return bool(dev.call(CENTURION_MIC_MUTE, 0)[0] & 1)


def set_centurion_mic_muted(dev, muted):
	dev.call(CENTURION_MIC_MUTE, 1, bytes([1 if muted else 0]))


# 0x0611 HeadsetMicGain (Centurion): fn 0 info [min, max] (decoder 0x141cddf10; which byte is min is
# from the order of G HUB's min_mic_gain / max_mic_gain fields: ours), fn 1 get [gain], fn 2 set [gain].
CENTURION_MIC_GAIN = 0x0611


def centurion_mic_gain(dev):
	"""(gain, min, max) in the headset's own units."""
	info = dev.call(CENTURION_MIC_GAIN, 0)
	return dev.call(CENTURION_MIC_GAIN, 1)[0], info[0], info[1]


def set_centurion_mic_gain(dev, gain):
	_gain, low, high = centurion_mic_gain(dev)
	dev.call(CENTURION_MIC_GAIN, 2, bytes([max(low, min(high, int(gain)))]))


# 0x0605 HeadsetAudioANC (Centurion): fn 0 get mode [mode], fn 1 set [mode], fn 2 get button, fn 3
# set button [short-press bits, long-press mode]. Modes on the wire = G HUB's HeadsetANC.Mode - 1
# (toDevio 0x14221e600); short-press bit n = the button cycles through mode n (encoder 0x141ed4f50).
CENTURION_ANC = 0x0605
ANC_MODES = ('Off', 'On', 'Transparency', 'Low', 'Adaptive')   # DISABLED, ENABLED, TRANSPARENCY, LOW, ADAPTIVE


def anc_mode(dev):
	return dev.call(CENTURION_ANC, 0)[0]


def set_anc_mode(dev, mode):
	dev.call(CENTURION_ANC, 1, bytes([mode]))


def anc_button(dev):
	"""(modes the button cycles through by a short press, the long-press mode)."""
	r = dev.call(CENTURION_ANC, 2)
	return [m for m in range(len(ANC_MODES)) if r[0] >> m & 1], r[1]


def set_anc_button(dev, short_modes, long_mode):
	dev.call(CENTURION_ANC, 3, bytes([sum(1 << m for m in short_modes), long_mode]))


# Switches of the newer headsets, as G HUB's devio classes send them (request function numbers from
# their methods; device values = G HUB's protobuf enum - 1, its toDevio / toProto): 0x060E AI noise
# reduction (fn 0 / 1 get / set on, fn 2 / 3 get / set level: off, low, medium, high), 0x0618 battery
# saver ("eco mode", fn 0 / 1), 0x0639 footstep detection (fn 0 / 1), 0x060B tones (getToneEnabledState
# fn 0, setToneEnabledState fn 1). That a get answers in byte 0 is ours.
# 0x0631 Do Not Disturb (fn 0 / 1, proto DoNotDisturb{is_donotdisturb_enabled}) works the same way.
AI_NOISE_REDUCTION, BATTERY_SAVER, FOOTSTEP_DETECTION, TONES, DO_NOT_DISTURB = 0x060E, 0x0618, 0x0639, 0x060B, 0x0631
AI_NR_LEVELS = ('Off', 'Low', 'Medium', 'High')
SWITCHES = {AI_NOISE_REDUCTION: 'AI noise reduction', BATTERY_SAVER: 'Battery saver',
            FOOTSTEP_DETECTION: 'Footstep detection', TONES: 'Headset tones', DO_NOT_DISTURB: 'Do not disturb'}


def switch_state(dev, feature):
	return bool(dev.call(feature, 0)[0])


def set_switch(dev, feature, on):
	dev.call(feature, 1, bytes([1 if on else 0]))


def ai_nr_level(dev):
	return dev.call(AI_NOISE_REDUCTION, 2)[0]


def set_ai_nr_level(dev, level):
	dev.call(AI_NOISE_REDUCTION, 3, bytes([max(0, min(len(AI_NR_LEVELS) - 1, level))]))


def switches(dev):
	"""{feature: on} for the switches this headset has, plus 'ai_level' with AI noise reduction."""
	out = {f: switch_state(dev, f) for f in SWITCHES if dev.has(f)}
	if AI_NOISE_REDUCTION in out:
		out['ai_level'] = ai_nr_level(dev)
	return out


# 0x063C AuxConfig (fn 0 get, fn 1 set; proto ALWAYS_ENABLED / ONLY_WHEN_DOCKED, wire = enum - 1) and
# 0x063A USBPortConfig (fn 0 getInfo: proto Info{count, ports{console_supported, pc_supported}},
# fn 1 getPortConfig [index], fn 2 setPortConfig [index, setting]; settings PC 0, CONSOLE 1 on the wire).
# Ours: info as [count, (pc, console) per port], answers in byte 0.
AUX_CONFIG, USB_PORTS = 0x063C, 0x063A
AUX_MODES = ('Always on', 'Only when docked')
PORT_SETTINGS = ('PC', 'Console')


def aux_mode(dev):
	return dev.call(AUX_CONFIG, 0)[0]


def set_aux_mode(dev, mode):
	dev.call(AUX_CONFIG, 1, bytes([mode]))


def usb_ports(dev):
	"""[(port index, setting)] of the headset's USB ports."""
	count = dev.call(USB_PORTS, 0)[0]
	return [(i, dev.call(USB_PORTS, 1, bytes([i]))[0]) for i in range(count)]


def set_usb_port(dev, index, setting):
	dev.call(USB_PORTS, 2, bytes([index, setting]))


# 0x063B MicSelect (G HUB's Feature063BMicSelect): fn 0 getInfo (proto Info{count, mic_types}), fn 1
# getActiveMic, fn 2 setActiveMic [index]. Mic types on the wire = G HUB's MicType - 1 (toProtoMicType).
# Ours: info as [count, type per mic], the active index in byte 0.
MIC_SELECT = 0x063B
MIC_TYPES = {0: 'Headset mic (wireless)', 1: 'USB mic', 2: 'Headset mic (cable)'}


def mics(dev):
	"""([mic names], active index)."""
	r = dev.call(MIC_SELECT, 0)
	names = [MIC_TYPES.get(t, f'Mic {i + 1}') for i, t in enumerate(r[1:1 + r[0]])]
	return names, dev.call(MIC_SELECT, 1)[0]


def set_mic(dev, index):
	dev.call(MIC_SELECT, 2, bytes([index]))


# 0x0604 HeadsetAudioSidetone (Centurion headsets; G HUB's FeatureC0604HeadsetSidetone): fn 0 get
# = [n, n x (mic, level)] ([mic, ?, level] from version 2), fn 1 set = [mic, 0xFF (version 2+),
# level], fn 2 settings: byte 2 = the number of steps (version 2+; 101 before). G HUB shows
# round(level * 100 / (steps - 1)) and only handles one mic (mic 0 here: ours, the first entry).
CENTURION_SIDETONE = 0x0604
OLD_STEPS = 101


def _sidetone_version(dev):
	return dev.request(0, 0, CENTURION_SIDETONE.to_bytes(2, 'big'))[2]


def _sidetone_steps(dev, version):
	return dev.call(CENTURION_SIDETONE, 2)[2] if version >= 2 else OLD_STEPS


def centurion_sidetone(dev):
	"""(level in percent) of the first mic."""
	version = _sidetone_version(dev)
	r = dev.call(CENTURION_SIDETONE, 0)
	level = r[3] if version >= 2 else r[2]
	steps = _sidetone_steps(dev, version)
	return round(level * 100 / (steps - 1)) if steps > 1 else 0


def set_centurion_sidetone(dev, percent):
	version = _sidetone_version(dev)
	steps = _sidetone_steps(dev, version)
	mic = dev.call(CENTURION_SIDETONE, 0)[1]
	level = round(max(0, min(100, percent)) * (steps - 1) / 100)        # G HUB's scale, inverted (ours)
	dev.call(CENTURION_SIDETONE, 1, bytes([mic, 0xFF, level] if version >= 2 else [mic, level]))
