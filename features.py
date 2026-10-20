"""HID++ 2.0 features shared by keyboards, headsets, speakers and wireless devices: battery,
lighting zones, brightness. Every function talks to the device; call from a worker thread."""
import struct
from dataclasses import dataclass, field

import battery_model
import hidpp
import store

BATTERY_STATUS = 0x1000      # level and charging state
BATTERY_VOLTAGE = 0x1001
UNIFIED_BATTERY = 0x1004
ADC_MEASUREMENT = 0x1F20      # voltage on older wireless headsets
COLOR_LED_EFFECTS = 0x8070
RGB_EFFECTS = 0x8071
BRIGHTNESS = 0x8040
ONBOARD = 0x8100
REPORT_RATE = 0x8060
SIDETONE = 0x8300
POLAR_PATTERN = 0x8330
ANGLE_SNAPPING = 0x2230
FN_INVERSION = 0x40A3
ANALOG_KEYS = 0x1B08
REPROG_CONTROLS = 0x1B04
ILLUMINATION = 0x1990
DISABLE_KEYS = 0x4522
DISABLE_KEYS_V1 = 0x4521
CHANGE_HOST = 0x1814
HOSTS_INFO = 0x1815
DEVICE_EQ = 0x8310
BUTTON_SWAP, HYBRID_TRACKING, CHARGING_CONTROL = 0x2005, 0x2400, 0x1010
BASS_TONE = 0x8305
BUNNY_HOPPING = 0x80E0
MIC_GAIN_ADJUST = 0x8370
HEADPHONE_ADJUST = 0x8360
MIC_BLEND = 0x8350
JACK_DETECTION = 0x8320
MUTE_INVERTED = ('046d:0ad1', '046d:0ad2')   # G HUB: on these 1 = muted, elsewhere 1 = mic on
BHOP_MIN, BHOP_MAX, BHOP_STEP = 100, 1000, 100     # G HUB's slider, ms

NAMES = {
	0x0000: 'Root', 0x0001: 'Feature set', 0x0002: 'Feature info', 0x0003: 'Firmware info',
	0x0005: 'Name and type', 0x0007: 'Friendly name', 0x0008: 'Keep alive', 0x0020: 'Config change',
	0x00C2: 'DFU control', 0x00D0: 'DFU', 0x1000: 'Battery', 0x1001: 'Battery voltage',
	0x1004: 'Battery', 0x1814: 'Change host', 0x1815: 'Hosts info', 0x1B04: 'Special keys and buttons', 0x1990: 'Light (Litra)',
	0x1D4B: 'Wireless status', 0x1F20: 'Battery (ADC)', 0x2201: 'Adjustable DPI', 0x2202: 'Extended DPI',
	0x2230: 'Angle snapping', 0x2250: 'Analysis mode', 0x40A3: 'Fn inversion', 0x4100: 'Encryption', 0x4220: 'Lock key state',
	0x4521: 'Disable keys', 0x4522: 'Game mode', 0x4540: 'Keyboard layout', 0x8010: 'G-keys',
	0x8020: 'M-keys', 0x8030: 'MR key', 0x8040: 'Brightness', 0x8060: 'Report rate',
	0x8061: 'Report rate', 0x8070: 'Lighting', 0x8071: 'RGB effects', 0x8080: 'Per-key lighting',
	0x8081: 'Per-key lighting', 0x8090: 'Mode status', 0x8100: 'Onboard profiles', 0x8110: 'Mouse button spy',
	0x8300: 'Sidetone', 0x8310: 'Equalizer', 0x8320: 'Headset out', 0x8330: 'Polar pattern',
	0x8350: 'Mic monitoring', 0x8360: 'Headphone level', 0x8370: 'Mic gain',
}

# --- battery -------------------------------------------------------------------------------

CHARGING = {0: 'On battery', 1: 'Charging', 2: 'Almost full', 3: 'Charged', 4: 'Charging slowly'}


def battery(dev, curves=None):
	"""(percent or None, text) or None when the device reports no battery. curves: the device's
	battery_model.parse() result, to turn a voltage into a percentage as G HUB does."""
	try:
		if dev.has(UNIFIED_BATTERY):
			r = dev.call(UNIFIED_BATTERY, 1)
			return r[0], CHARGING.get(r[2], '')
		if dev.has(BATTERY_STATUS):
			r = dev.call(BATTERY_STATUS, 0)
			return r[0], CHARGING.get(r[2], '')
		if dev.has(BATTERY_VOLTAGE):
			r = dev.call(BATTERY_VOLTAGE, 0)
			return _from_volts(struct.unpack('>H', r[:2])[0], bool(r[2] & 0x80), curves)
		if dev.has(ADC_MEASUREMENT):
			# fn 0 (channel) -> [millivolts u16, flags]; G HUB reads flag bits 1 and 2, bit 1 taken
			# as charging (ours)
			r = dev.call(ADC_MEASUREMENT, 0, b'\0')
			return _from_volts(struct.unpack('>H', r[:2])[0], bool(r[2] & 2), curves)
	except hidpp.HidppError:
		return None
	return None


def _from_volts(mv, charging, curves):
	text = CHARGING[1] if charging else CHARGING[0]
	if curves:
		return battery_model.percent(curves, mv / 1000, charging), text
	return None, f'{mv / 1000:.2f} V' + (' · charging' if charging else '')


# --- lighting (0x8070) ---------------------------------------------------------------------

# HID++ effect ids as G HUB's feature_8070 / feature_8071_lighting_effects read them (its own
# names from its en-US strings); 2 "Pulse" isn't in G HUB's list (ours, kept from before).
EFFECTS = {0: 'Off', 1: 'Fixed', 2: 'Pulse', 3: 'Color cycle', 4: 'Color wave', 10: 'Breathing', 11: 'Ripple',
           12: 'Custom', 13: 'KITT', 14: 'Color blend', 15: 'Signature', 16: 'Signature (idle)',
           17: 'Pulsar Point', 18: 'Neutron Null', 19: 'Streaming', 21: 'Color cycle (smooth)',
           22: 'Color wave (smooth)', 23: 'Ripple (smooth)', 24: 'Signature', 25: 'Signature (idle)',
           26: 'Signature (built in)', 27: 'Signature (built in, idle)', 28: 'Key travel glow'}
FIXED, PULSE, CYCLE, COLOR_WAVE, BREATHING, RIPPLE = 1, 2, 3, 4, 10, 11
SIGNATURE_FRAME = (15, 16)
TWO_COLOR = (17, 18, 24, 25)            # G HUB's DualColor: Pulsar Point, Neutron Null, signature
SIGNATURE_STYLES = (24, 25)              # ... whose last byte picks the style
KEY_TRAVEL_GLOW = 28
NEEDS_COLOR = {FIXED, PULSE, BREATHING, RIPPLE, KEY_TRAVEL_GLOW} | set(TWO_COLOR)
NEEDS_COLOR2 = {KEY_TRAVEL_GLOW} | set(TWO_COLOR)
NEEDS_SPEED = {PULSE, CYCLE, COLOR_WAVE, BREATHING, RIPPLE} | set(SIGNATURE_FRAME)
TWO_COLOR_PERIOD = 50     # ms: G HUB's default for these (the G515's defaults_override.json); no setting of ours
NEEDS_BRIGHTNESS = {PULSE, CYCLE, COLOR_WAVE, BREATHING} | set(SIGNATURE_FRAME) | set(TWO_COLOR)
# G HUB's ColorWave directions (1-8) and signature styles (its SignatureAlgorithmicEffect types)
DIRECTIONS = {1: 'Horizontal', 2: 'Vertical', 3: 'Center out', 4: 'Inward', 5: 'Outward',
              6: 'Reverse horizontal', 7: 'Reverse vertical', 8: 'Center in'}
STYLES = {0: 'IMMERSE', 1: 'Pulsar Point', 2: 'G3 Signature', 3: 'Reminds Me Of', 4: 'Neon', 5: 'Outer Space'}
ZONE_LOCATIONS = {0: 'Main', 1: 'Main', 2: 'Logo', 3: 'Left side', 4: 'Right side', 5: 'Combined',
                  6: 'Primary 1', 7: 'Primary 2', 8: 'Primary 3', 9: 'Primary 4', 10: 'Primary 5',
                  11: 'Primary 6'}


@dataclass
class Zone:
	index: int
	location: int
	effects: list = field(default_factory=list)   # [(effect index, effect id)]
	feature: int = COLOR_LED_EFFECTS              # 0x8070, or 0x8071 on newer devices

	@property
	def name(self):
		return ZONE_LOCATIONS.get(self.location, f'Zone {self.index + 1}')


def zones(dev):
	"""Lighting zones and the effects each one offers (0x8070)."""
	count = dev.call(COLOR_LED_EFFECTS, 0)[0]
	found = []
	for z in range(count):
		r = dev.call(COLOR_LED_EFFECTS, 1, bytes([z]))
		zone = Zone(r[0], struct.unpack('>H', r[1:3])[0])
		for e in range(r[3]):
			info = dev.call(COLOR_LED_EFFECTS, 2, bytes([z, e]))
			zone.effects.append((info[1], struct.unpack('>H', info[2:4])[0]))
		found.append(zone)
	return found


def zones_v2(dev):
	"""The same from 0x8071 RGB effects, as G HUB's Feature8071RGBEffects asks: fn 0 with (0xFF,
	0xFF) = device info (byte 2 = cluster count), (cluster, 0xFF) = cluster info (location,
	effect count), (cluster, effect) = effect info (its id)."""
	count = dev.call(RGB_EFFECTS, 0, bytes([0xFF, 0xFF, 0]))[2]
	found = []
	for c in range(count):
		r = dev.call(RGB_EFFECTS, 0, bytes([c, 0xFF, 0]))
		zone = Zone(c, struct.unpack('>H', r[2:4])[0], feature=RGB_EFFECTS)
		for e in range(r[4]):
			info = dev.call(RGB_EFFECTS, 0, bytes([c, e, 0]))
			zone.effects.append((e, struct.unpack('>H', info[2:4])[0]))
		found.append(zone)
	return found


def effect_params(effect_id, color=(255, 255, 255), period=3000, brightness=100, color2=(0, 0, 0),
                  direction=1, style=0):
	"""The 10 parameter bytes of an effect, as G HUB's get_raw_effect_params builds them (the same
	for 0x8070 and 0x8071). Pulse is ours (not in G HUB); so is Ripple's byte 3 left 0."""
	r, g, b = color
	period = max(1000, min(20000, int(period)))
	brightness = max(1, min(100, int(brightness)))
	hi, lo = period >> 8, period & 0xFF
	if effect_id == FIXED:
		data = bytes([r, g, b, 2])
	elif effect_id in (BREATHING, PULSE):
		data = bytes([r, g, b, hi, lo, 0, brightness])
	elif effect_id == CYCLE or effect_id in SIGNATURE_FRAME:
		data = bytes([0, 0, 0, 0, 0, hi, lo, brightness])
	elif effect_id == COLOR_WAVE:            # the period's two bytes are split around direction and brightness
		data = bytes([0, 0, 0, 0, 0, 0, lo, direction, brightness, hi])
	elif effect_id == RIPPLE:
		data = bytes([r, g, b, 0, hi, lo])
	elif effect_id in TWO_COLOR:
		data = bytes([r, g, b, *color2, *struct.pack('>H', TWO_COLOR_PERIOD), brightness,
		              style if effect_id in SIGNATURE_STYLES else 0])
	elif effect_id == KEY_TRAVEL_GLOW:
		data = bytes([r, g, b, *color2, 100, 100])
	else:
		data = b''
	return data.ljust(10, b'\0')


def set_effect(dev, zone, effect_index, params, persist=True, feature=COLOR_LED_EFFECTS):
	"""0x8070 fn 3, or 0x8071 fn 1 (SetEffectByIndex: cluster, effect, then the parameters; that
	they take 0x8070's parameter bytes and persist flag is ours)."""
	fn = 1 if feature == RGB_EFFECTS else 3
	dev.call(feature, fn, bytes([zone, effect_index]) + params + bytes([1 if persist else 0]))


# --- polar pattern (0x8330, Yeti mics) -----------------------------------------------------
# As G HUB's Feature8330MicrophonePolarPattern: fn 0 = bitmask of supported patterns (bit n ->
# pattern n + 1), fn 1 = current pattern, fn 2 = set; the device also reports changes (event 0).

PATTERNS = {1: 'Stereo', 2: 'Cardioid', 3: 'Bidirectional', 4: 'Omnidirectional'}


def polar_patterns(dev):
	"""(supported pattern numbers, current pattern)."""
	mask = dev.call(POLAR_PATTERN, 0)[0]
	return [p for p in PATTERNS if mask >> (p - 1) & 1], dev.call(POLAR_PATTERN, 1)[0]


def set_polar_pattern(dev, pattern):
	dev.call(POLAR_PATTERN, 2, bytes([pattern]))


# --- small switches G HUB offers (function layouts from its Feature2230 / 40A3 / 4522 classes) ----

def angle_snapping(dev):
	return dev.call(ANGLE_SNAPPING, 0)[0] == 1


def set_angle_snapping(dev, on):
	dev.call(ANGLE_SNAPPING, 1, bytes([1 if on else 0]))


def fn_inversion(dev, host=0):
	"""(inverted, default) for a host (fn 0: host, state, default, capabilities)."""
	r = dev.call(FN_INVERSION, 0, bytes([host]))
	return bool(r[1]), bool(r[2])


def set_fn_inversion(dev, on, host=0):
	dev.call(FN_INVERSION, 1, bytes([host, 1 if on else 0]))


# Special keys and mouse buttons (0x1B04), as G HUB's Feature1B04SpecialKeys: fn 0 count, fn 1
# control info, fn 2 / fn 3 get / set reporting; fn 3 sends [cid u16, flags, remap u16, flags2]
# (G HUB's SetCtrlIdReporting). Bit meanings from Logitech's HID++ spec for 0x1B04: in fn 1's
# flags 0x20 = divertable, in fn 3's flags 0x01 = divert and 0x02 = "divert is valid". A diverted
# control is reported to software (event 0: up to four control ids held, u16 each) instead of
# doing its own job. fn 1 also gives the control's position: mouse button n has position n.
DIVERTABLE, DIVERT, DIVERT_VALID = 0x20, 0x01, 0x02


@dataclass
class Control:
	cid: int
	task: int
	flags: int
	position: int


def controls(dev):
	"""The device's controls (0x1B04 fn 0 / fn 1)."""
	found = []
	for i in range(dev.call(REPROG_CONTROLS, 0)[0]):
		r = dev.call(REPROG_CONTROLS, 1, bytes([i]))
		cid, task = struct.unpack('>HH', r[:4])
		found.append(Control(cid, task, r[4], r[5]))
	return found


def set_diverted(dev, cid, on):
	"""Report the control to software (on) or let it do its own job again (off)."""
	dev.call(REPROG_CONTROLS, 3, struct.pack('>HBHB', cid, DIVERT_VALID | (DIVERT if on else 0), 0, 0))


def diverted_held(params):
	"""Control ids held, from a 0x1B04 diverted-controls event."""
	return [c for c in struct.unpack('>4H', bytes(params[:8]).ljust(8, b'\0')) if c]


# Litra lights (0x1990), as G HUB's Feature1990IlluminationLight: fn 0 / fn 1 get / set the light
# on (one byte), fn 2 brightness info and fn 7 colour-temperature info ([flags, minimum u16, maximum
# u16, step u16, levels]: minimum and maximum in G HUB's RangeUInt order; the third as the step is
# ours), fn 3 / fn 4 get / set brightness, fn 8 / fn 9 get / set colour temperature (u16 big-endian,
# lumens and kelvin), fn 12 the effective maximum brightness.
def _range(r):
	low, high, step = struct.unpack('>HHH', bytes(r[1:7]))
	return low, high, step or 1


def illumination(dev):
	"""{'on', 'brightness', 'brightness_range', 'temperature', 'temperature_range'} of a Litra."""
	brightness_range = _range(dev.call(ILLUMINATION, 2))
	effective = struct.unpack('>H', bytes(dev.call(ILLUMINATION, 0xC)[:2]))[0]
	if effective and brightness_range[0] < effective < brightness_range[1]:
		brightness_range = (brightness_range[0], effective, brightness_range[2])
	return {'on': bool(dev.call(ILLUMINATION, 0)[0] & 1),
	        'brightness': struct.unpack('>H', bytes(dev.call(ILLUMINATION, 3)[:2]))[0],
	        'brightness_range': brightness_range,
	        'temperature': struct.unpack('>H', bytes(dev.call(ILLUMINATION, 8)[:2]))[0],
	        'temperature_range': _range(dev.call(ILLUMINATION, 7))}


def set_illumination(dev, on):
	dev.call(ILLUMINATION, 1, bytes([1 if on else 0]))


def set_light_brightness(dev, lumens):
	dev.call(ILLUMINATION, 4, struct.pack('>H', int(lumens)))


def set_color_temperature(dev, kelvin):
	dev.call(ILLUMINATION, 9, struct.pack('>H', int(kelvin)))


# Analog keyboards' switches (0x1B08), as G HUB's Feature1B08AnalogKeys: fn 0 capabilities, fn 1 /
# fn 2 get / set rapid trigger, fn 3 key-travel events, fn 4 / fn 5 get / set key priority; a set
# sends one byte, bit 0 = on. That a get answers the same bit is ours (G HUB reads it in code not
# decoded yet). Actuation points and rapid-trigger sensitivity per key live in the onboard profile
# (0x8101 / 0x8102), not here.
def analog_switches(dev):
	"""{'rapid_trigger': bool, 'key_priority': bool}."""
	return {'rapid_trigger': bool(dev.call(ANALOG_KEYS, 1)[0] & 1),
	        'key_priority': bool(dev.call(ANALOG_KEYS, 4)[0] & 1)}


def set_rapid_trigger(dev, on):
	dev.call(ANALOG_KEYS, 2, bytes([1 if on else 0]))


def set_key_priority(dev, on):
	dev.call(ANALOG_KEYS, 5, bytes([1 if on else 0]))


# The headset's own equalizer (0x8310), as G HUB's Feature8310Equalizer: fn 0 getEQInfo (count,
# dbRange, capabilities, dbMin, dbMax), fn 1 frequencies from a band index (index, then 16-bit
# big-endian Hz), fn 2 gains (signed dB, one byte each), fn 3 set gains (G HUB sends 2, then the
# gains), fn 4 / fn 5 read / set whether it's on.

def device_eq(dev):
	"""{'freqs', 'gains', 'low', 'high', 'on'} of the headset's own equalizer."""
	info = dev.call(DEVICE_EQ, 0)
	count = info[0]
	low, high = struct.unpack('bb', info[3:5])
	freqs = []
	while len(freqs) < count:
		r = dev.call(DEVICE_EQ, 1, bytes([len(freqs)]))
		got = [struct.unpack('>H', r[1 + 2 * i:3 + 2 * i])[0] for i in range(min(7, count - len(freqs)))]
		if not any(got):
			break
		freqs += got
	gains = list(struct.unpack(f'{count}b', dev.call(DEVICE_EQ, 2)[:count]))
	return {'freqs': freqs, 'gains': gains, 'low': low or -12, 'high': high or 12,
	        'on': bool(dev.call(DEVICE_EQ, 4)[0])}


def set_device_eq(dev, gains):
	dev.call(DEVICE_EQ, 3, bytes([2]) + struct.pack(f'{len(gains)}b', *(round(g) for g in gains)))


def set_device_eq_on(dev, on):
	dev.call(DEVICE_EQ, 5, bytes([1 if on else 0]))


# Left-handed (0x2005 ButtonSwapCancel: fn 0 read, fn 1 SetSwapMode), hybrid tracking (0x2400:
# fn 0 IsHybridEngineEnabled, fn 2 / fn 3 Get / SetHybridReportingMode, 0 = low latency,
# 1 = power save as G HUB's ModeStatus.HybridType), charging control (0x1010: fn 0 / fn 1, on/off
# as G HUB's ChargeControl). Function names from G HUB's log strings.
HYBRID_MODES = ((0, 'Low latency'), (1, 'Power saving'))


def button_swap(dev):
	return bool(dev.call(BUTTON_SWAP, 0)[0])


def set_button_swap(dev, on):
	dev.call(BUTTON_SWAP, 1, bytes([1 if on else 0]))


def hybrid_mode(dev):
	"""The hybrid reporting mode, or None when the hybrid engine is off."""
	if dev.call(HYBRID_TRACKING, 0)[0] != 1:
		return None
	mode = dev.call(HYBRID_TRACKING, 2)[0]
	return mode if mode in (0, 1) else None


def set_hybrid_mode(dev, mode):
	dev.call(HYBRID_TRACKING, 3, bytes([mode]))


def charging(dev):
	return bool(dev.call(CHARGING_CONTROL, 0)[0])


def set_charging(dev, on):
	dev.call(CHARGING_CONTROL, 1, bytes([1 if on else 0]))


# Bass tone (0x8305): fn 0 get, fn 1 set the level, 0-100; G HUB's subwoofer bass volume (0-1)
# times 100 (Feature8305BassTone::_ApplyBassToneLevel).

def bass_tone(dev):
	return dev.call(BASS_TONE, 0)[0]


def set_bass_tone(dev, level):
	dev.call(BASS_TONE, 1, bytes([max(0, min(100, int(level)))]))


# Bunny hopping (0x80E0, G HUB's Feature80E0BunnyHopping): fn 1 get, fn 2 set the timeout in
# 10 ms steps, up to 2540 ms; 0 = off (G HUB won't switch it on with a 0 ms timeout). G HUB's page:
# a switch and a 100-1000 ms slider in 100 ms steps.

def bunny_hopping(dev):
	"""The timeout in ms, 0 when off."""
	return dev.call(BUNNY_HOPPING, 1)[0] * 10


def set_bunny_hopping(dev, ms):
	dev.call(BUNNY_HOPPING, 2, bytes([max(0, min(254, int(ms) // 10))]))


# Mic gain and mute (0x8370 MicrophoneGainAdjust, Yetis), as G HUB's
# feature_8370_microphone_gain_adjust: fn 0 = channel count, fn 1 (channel) = [?, control count],
# fn 2 (channel, control) = [?, ?, type, value], fn 3 (channel, type, value) sets one. Types:
# 0 mute, 1 / 2 gain (value = G HUB's 0-1 gain x 100), 5 a switch G HUB keeps but doesn't show.
# G HUB writes channel 0, gain with the type the mic reported (2 if none).

def _adjust_controls(dev, feature):
	"""(type, value) of every control on every channel, as G HUB walks them (0x8360 / 0x8370)."""
	for channel in range(dev.call(feature, 0)[0]):
		for control in range(dev.call(feature, 1, bytes([channel]))[1]):
			r = dev.call(feature, 2, bytes([channel, control]))
			yield r[2], r[3]


def mic_gain_adjust(dev, usb_id=''):
	"""{'muted': bool, 'gain': 0-100, 'gain_type': 1 or 2}, with what the mic has."""
	out = {}
	for kind, value in _adjust_controls(dev, MIC_GAIN_ADJUST):
		if kind == 0:
			out['muted'] = (value == 1) if usb_id in MUTE_INVERTED else (value == 0)
		elif kind in (1, 2):
			out['gain'], out['gain_type'] = value, kind
	return out


def set_mic_muted(dev, muted, usb_id=''):
	on = muted if usb_id in MUTE_INVERTED else not muted
	dev.call(MIC_GAIN_ADJUST, 3, bytes([0, 0, 1 if on else 0]))


def set_mic_gain(dev, percent, gain_type=2):
	dev.call(MIC_GAIN_ADJUST, 3, bytes([0, gain_type, max(0, min(100, int(percent)))]))


# Headphone level (0x8360 MicrophoneHeadphoneAdjust, Yetis): the same functions as 0x8370; type 2
# is the level (G HUB's 0-1 x 100), the only one G HUB writes (channel 0).

def headphone_level(dev):
	return next((value for kind, value in _adjust_controls(dev, HEADPHONE_ADJUST) if kind == 2), None)


def set_headphone_level(dev, percent):
	dev.call(HEADPHONE_ADJUST, 3, bytes([0, 2, max(0, min(100, int(percent)))]))


# Mic monitoring (0x8350 MicrophoneBlendAdjust, Yetis: how much of the mic goes to the
# headphones), as G HUB's sidetone code: fn 0 = count; fn 1 (i, i) = [?, ?, active, level];
# fn 2 (0, 1, level) sets it. Level = G HUB's 0-1 x 100.

def mic_monitoring(dev):
	for i in range(dev.call(MIC_BLEND, 0)[0]):
		r = dev.call(MIC_BLEND, 1, bytes([i, i]))
		if r[2]:
			return r[3]
	return None


def set_mic_monitoring(dev, percent):
	dev.call(MIC_BLEND, 2, bytes([0, 1, max(0, min(100, int(percent)))]))


# Jack detection (0x8320, G HUB's Feature8320JackDetection::getJackStatus): fn 0 = [jacks in use,
# jacks there], one bit per jack. Bit 0 taken as the headphone jack (ours).

def headphones_plugged(dev):
	r = dev.call(JACK_DETECTION, 0)
	return bool(r[0] & r[1] & 1) if r[1] & 1 else None


# Easy-Switch (0x1814 ChangeHost): fn 0 = host count, current host; fn 1 = switch to a host. The
# device leaves for the other computer at once, so there's no answer to wait for (as in G HUB).

def hosts(dev):
	r = dev.call(CHANGE_HOST, 0)
	return r[0], r[1]


def host_name(dev, host):
	"""A host's name (0x1815 GetHostInfos, then GetHostFriendlyName in 14-byte pieces), or None.
	G HUB's functions; which reply bytes hold the length and the text is ours."""
	try:
		length = min(dev.call(HOSTS_INFO, 1, bytes([host]))[4], 64)
		name = b''
		while len(name) < length:
			chunk = dev.call(HOSTS_INFO, 2, bytes([host, len(name)]))[2:16]
			if not chunk.strip(b'\0'):
				break
			name += chunk
		text = name[:length].split(b'\0')[0].decode('utf-8', 'replace').strip()
	except hidpp.HidppError:
		return None
	return text if text and text.isprintable() else None


def set_host(dev, host):
	try:
		dev.call(CHANGE_HOST, 1, bytes([host]))
	except hidpp.NoReply:
		pass


# Game mode (0x4522 DisableKeysByUsage): fn 0 = how many keys can be off, fn 1 = turn these HID
# usages off, fn 2 = back on, fn 3 = all back on. The keyboard doesn't report which are off.
GAME_MODE_KEYS = ((0xE3, 'Left Windows'), (0xE7, 'Right Windows'), (0x65, 'Menu'), (0x39, 'Caps Lock'))


GAME_MODE_FILE = 'game_mode.json'      # in store.CONFIG_DIR: {model key: [HID usages]}


def game_mode_keys(model):
	return store._read_json(f'{store.CONFIG_DIR}/{GAME_MODE_FILE}', {}).get(model, [])


def save_game_mode_keys(model, keys):
	path = f'{store.CONFIG_DIR}/{GAME_MODE_FILE}'
	data = store._read_json(path, {})
	data[model] = keys
	store._write_json(path, data)


# Older keyboards (0x4521 DisableKeys): five fixed keys, one bit each; fn 0 = the ones the keyboard
# has, fn 1 = the ones off now, fn 2 = set (G HUB's Feature4521DisableKeys: bits 4..0). Which key
# each bit is comes from Logitech's HID++ 0x4521 spec, not G HUB.
KEYS_V1 = ((0x01, 0x39, 'Caps Lock'), (0x02, 0x53, 'Num Lock'), (0x04, 0x47, 'Scroll Lock'),
           (0x08, 0x49, 'Insert'), (0x10, 0xE3, 'Windows'))


def game_mode_choices(dev):
	"""(how many keys can be off, [(usage, name)]) for the keyboard's game mode."""
	if dev.has(DISABLE_KEYS):
		return max_disabled_keys(dev), list(GAME_MODE_KEYS)
	have = dev.call(DISABLE_KEYS_V1, 0)[0]
	keys = [(usage, name) for bit, usage, name in KEYS_V1 if have & bit]
	return len(keys), keys


def apply_game_mode(dev, usages):
	"""Turn these keys off (and the others back on), on either kind of keyboard."""
	if dev.has(DISABLE_KEYS):
		set_disabled_keys(dev, usages)
	elif dev.has(DISABLE_KEYS_V1):
		mask = sum(bit for bit, usage, _n in KEYS_V1 if usage in usages)
		dev.call(DISABLE_KEYS_V1, 2, bytes([mask]))


def max_disabled_keys(dev):
	return dev.call(DISABLE_KEYS, 0)[0]


def set_disabled_keys(dev, usages):
	dev.call(DISABLE_KEYS, 3)
	if usages:
		dev.call(DISABLE_KEYS, 1, bytes(usages))


# --- brightness (0x8040) -------------------------------------------------------------------

def brightness(dev):
	"""(current, maximum)."""
	info = dev.call(BRIGHTNESS, 0)
	high = struct.unpack('>H', info[:2])[0] or 100
	return struct.unpack('>H', dev.call(BRIGHTNESS, 1)[:2])[0], high


def set_brightness(dev, value):
	dev.call(BRIGHTNESS, 2, struct.pack('>H', int(value)))


# --- receivers -----------------------------------------------------------------------------

@dataclass
class Paired:
	index: int
	name: str
	kind: str


def paired_devices(receiver_dev_factory):
	"""Ask slots 1-6 of a receiver who is there. receiver_dev_factory(index) gives a
	hidpp.Device for that slot on the receiver's interface."""
	found = []
	for index in range(1, 7):
		dev = receiver_dev_factory(index)
		try:
			dev.protocol_version()
			found.append(Paired(index, dev.name(), dev.kind()))
		except hidpp.HidppError:
			continue
	return found
