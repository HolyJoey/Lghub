"""HID++ 2.0 features shared by keyboards, headsets, speakers and wireless devices: battery,
lighting zones, brightness. Every function talks to the device; call from a worker thread."""
import struct
from dataclasses import dataclass, field

import hidpp

BATTERY_STATUS = 0x1000      # level and charging state
BATTERY_VOLTAGE = 0x1001
UNIFIED_BATTERY = 0x1004
COLOR_LED_EFFECTS = 0x8070
RGB_EFFECTS = 0x8071
BRIGHTNESS = 0x8040
ONBOARD = 0x8100
REPORT_RATE = 0x8060
SIDETONE = 0x8300

NAMES = {
	0x0000: 'Root', 0x0001: 'Feature set', 0x0002: 'Feature info', 0x0003: 'Firmware info',
	0x0005: 'Name and type', 0x0007: 'Friendly name', 0x0008: 'Keep alive', 0x0020: 'Config change',
	0x00C2: 'DFU control', 0x00D0: 'DFU', 0x1000: 'Battery', 0x1001: 'Battery voltage',
	0x1004: 'Battery', 0x1814: 'Change host', 0x1815: 'Hosts info', 0x1B04: 'Special keys and buttons',
	0x1D4B: 'Wireless status', 0x1F20: 'Battery (ADC)', 0x2201: 'Adjustable DPI', 0x2202: 'Extended DPI',
	0x2250: 'Analysis mode', 0x40A3: 'Fn inversion', 0x4100: 'Encryption', 0x4220: 'Lock key state',
	0x4521: 'Disable keys', 0x4522: 'Game mode', 0x4540: 'Keyboard layout', 0x8010: 'G-keys',
	0x8020: 'M-keys', 0x8030: 'MR key', 0x8040: 'Brightness', 0x8060: 'Report rate',
	0x8061: 'Report rate', 0x8070: 'Lighting', 0x8071: 'RGB effects', 0x8080: 'Per-key lighting',
	0x8081: 'Per-key lighting', 0x8090: 'Mode status', 0x8100: 'Onboard profiles', 0x8110: 'Mouse button spy',
	0x8300: 'Sidetone', 0x8310: 'Equalizer', 0x8320: 'Headset out',
}

# --- battery -------------------------------------------------------------------------------

CHARGING = {0: 'On battery', 1: 'Charging', 2: 'Almost full', 3: 'Charged', 4: 'Charging slowly'}


def battery(dev):
	"""(percent or None, text) or None when the device reports no battery."""
	try:
		if dev.has(UNIFIED_BATTERY):
			r = dev.call(UNIFIED_BATTERY, 1)
			return r[0], CHARGING.get(r[2], '')
		if dev.has(BATTERY_STATUS):
			r = dev.call(BATTERY_STATUS, 0)
			return r[0], CHARGING.get(r[2], '')
		if dev.has(BATTERY_VOLTAGE):
			r = dev.call(BATTERY_VOLTAGE, 0)
			mv = struct.unpack('>H', r[:2])[0]
			charging = bool(r[2] & 0x80)
			return None, f'{mv / 1000:.2f} V' + (' · charging' if charging else '')
	except hidpp.HidppError:
		return None
	return None


# --- lighting (0x8070) ---------------------------------------------------------------------

EFFECTS = {0x0000: 'Off', 0x0001: 'Fixed', 0x0002: 'Pulse', 0x0003: 'Color cycle', 0x0008: 'Color wave',
           0x0009: 'Starlight', 0x000A: 'Breathing', 0x000B: 'Ripple', 0x000C: 'Audio visualizer',
           0x000D: 'Boot up', 0x000E: 'Demo'}
FIXED, PULSE, CYCLE, BREATHING = 0x0001, 0x0002, 0x0003, 0x000A
NEEDS_COLOR = {FIXED, PULSE, BREATHING}
NEEDS_SPEED = {PULSE, CYCLE, BREATHING}
ZONE_LOCATIONS = {0: 'Main', 1: 'Main', 2: 'Logo', 3: 'Left side', 4: 'Right side', 5: 'Combined',
                  6: 'Primary 1', 7: 'Primary 2', 8: 'Primary 3', 9: 'Primary 4', 10: 'Primary 5',
                  11: 'Primary 6'}


@dataclass
class Zone:
	index: int
	location: int
	effects: list = field(default_factory=list)   # [(effect index, effect id)]

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


def effect_params(effect_id, color=(255, 255, 255), period=3000, brightness=100):
	"""The 10 parameter bytes of an effect; same layouts as onboard profile lighting."""
	r, g, b = color
	period = max(1000, min(20000, int(period)))
	brightness = max(1, min(100, int(brightness)))
	if effect_id == FIXED:
		data = bytes([r, g, b, 0])
	elif effect_id in (BREATHING, PULSE):
		data = bytes([r, g, b]) + struct.pack('>H', period) + bytes([0, brightness])
	elif effect_id == CYCLE:
		data = bytes(5) + struct.pack('>H', period) + bytes([brightness])
	else:
		data = b''
	return data.ljust(10, b'\0')


def set_effect(dev, zone, effect_index, params, persist=True):
	dev.call(COLOR_LED_EFFECTS, 3, bytes([zone, effect_index]) + params + bytes([1 if persist else 0]))


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
