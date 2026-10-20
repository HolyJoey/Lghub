"""Battery percentage from a voltage, with G HUB's own curves (battery.xml in the device's depot,
read by G HUB's battery_model_voltage): a discharge curve of time, voltage and capacity used,
and a charging curve of voltage and state of charge (rising, then falling near full).

Discharging, the percentage is the capacity left at the first point of the curve whose voltage
is at or below the reading; charging, it's the state of charge at the reading. Picking the
nearest point instead of G HUB's exact interpolation is ours.
"""
import xml.etree.ElementTree as ET  # nosec B405 - G HUB's own file from its update server


def _rows(text):
	rows = []
	for line in (text or '').splitlines():
		parts = line.strip().split(',')
		try:
			rows.append(tuple(float(p) for p in parts))
		except ValueError:
			continue
	return [r for r in rows if r]


def parse(path):
	"""{'discharge': [(volts, used)], 'charging': [(volts, percent)]} or None."""
	try:
		root = ET.parse(path).getroot()   # nosec B314 - see above
	except (OSError, ET.ParseError):
		return None
	battery = root.find('battery')
	if battery is None:
		return None
	out = {'discharge': [], 'charging': []}
	discharge = battery.find('discharge')
	if discharge is not None:
		out['discharge'] = [(r[1], r[2]) for r in _rows(discharge.text) if len(r) >= 3]
	charging = battery.find('charging')
	if charging is not None:
		node = charging.find('ascending')    # the falling part near full is left out (ours)
		if node is not None:
			out['charging'] = [(r[0], r[1]) for r in _rows(node.text) if len(r) >= 2]
	return out if out['discharge'] else None


def for_device(device):
	"""The parsed curves for a devices.Device (downloaded once), or None. Blocks."""
	import depots
	path = depots.fetch_battery(device.model.key, device.usb_id.split(':')[-1])
	return parse(path) if path else None


def percent(model, volts, charging=False):
	"""0-100 for a reading in volts."""
	if charging and model['charging']:
		below = [p for v, p in model['charging'] if v <= volts]
		return round(max(below)) if below else 0
	curve = model['discharge']
	total = curve[-1][1] or 1
	used = next((u for v, u in curve if v <= volts), total)
	return max(0, min(100, round(100 * (1 - used / total))))


# Newer devices' battery.xml is a power model instead (<powermodel>): the battery's capacity in
# watt-hours and the power each part draws in milliwatts (sensor, MCU, roller, report rate,
# lighting, ...). G HUB adds up the parts for the device's current settings and estimates
# hours = percent / 100 * capacity * 1000 / milliwatts (its max_life_span at 100 %, "mileage" at
# the current percentage).
def _power(node, hz=None, lit=True):
	"""A block's milliwatts, with its report-rate override for hz (<report_rate hertz=...>) and, with
	the lights off, its <brightness percent="0"> one."""
	value = float(node.get('power', 0) or 0)
	for over in node.findall('report_rate'):
		if hz and over.get('hertz') and float(over.get('hertz')) == hz:
			value = float(over.get('power', value))
	if not lit:
		for over in node.findall('brightness'):
			if float(over.get('percent', -1)) == 0:
				value = float(over.get('power', value))
	return value


def parse_power(path):
	"""{'wh': capacity, 'blocks': root of <blocks>} for a power model, else None."""
	try:
		root = ET.parse(path).getroot()   # nosec B314 - see above
	except (OSError, ET.ParseError):
		return None
	capacity = root.find('battery/capacity')
	blocks = root.find('blocks')
	if root.tag != 'powermodel' or capacity is None or blocks is None:
		return None
	try:
		wh = float(capacity.get('watts_per_hour', 0))
	except ValueError:
		return None
	return {'wh': wh, 'blocks': blocks} if wh > 0 else None


def _lighting(lighting, lit):
	"""Lighting milliwatts: the busiest zone's "off" effect, or its solid colour at full brightness
	(the effect the device runs isn't read back, so on = solid 100 %: ours), plus the MCU load."""
	if lighting is None:
		return 0.0
	load = float(lighting.get('mcu_load', 0) or 0)
	best = 0.0
	for zone in lighting.findall('zone'):
		for effect in zone.findall('effect'):
			if not lit and effect.get('type') == 'off':
				best = max(best, float(effect.get('power', 0) or 0) + float(effect.get('mcu_load', 0) or 0))
			elif lit and effect.get('type') == 'solid':
				levels = [(float(b.get('percent', 0)), float(b.get('power', 0))) for b in effect.findall('brightness')]
				best = max([best] + [p for _pc, p in sorted(levels)[-1:]])
	return best + (load if lit else 0.0)


def milliwatts(model, hz=1000, lit=False):
	"""The device's draw: every block for the report rate, lighting off or on."""
	blocks = model['blocks']
	total = 0.0
	for node in blocks:
		if node.tag == 'lighting':
			total += _lighting(node, lit)
		elif node.tag == 'report_rate':
			intervals = [(float(i.get('milliseconds', 0)), i) for i in node.findall('interval')]
			if intervals:
				ms = 1000 / hz if hz else 1
				_ms, nearest = min(intervals, key=lambda t, want=ms: abs(t[0] - want))   # nearest interval: ours
				total += _power(nearest, None, lit)
		else:
			total += _power(node, hz, lit)
	return total


def hours_left(model, percent, hz=1000):
	"""(hours with the lights off, hours with them on) at percent; the same twice without lighting."""
	if not model or percent is None:
		return None
	out = []
	for lit in (False, True):
		mw = milliwatts(model, hz, lit)
		out.append(percent / 100 * model['wh'] * 1000 / mw if mw > 0 else 0)
	return tuple(out)


def life_text(model, percent, hz=1000, charging=False):
	"""'about 38 h left', or a range 'about 38-137 h left' when lighting matters (ours); '' if unknown."""
	hours = None if charging or not model else hours_left(model, percent, hz or 1000)
	if not hours or not hours[1]:
		return ''
	off, on = (round(h) for h in hours)
	return f'about {on} h left' if off == on else f'about {on}–{off} h left'


def life_for(device, battery, hz=None):
	"""life_text for a features.battery() result while on battery ('' otherwise). Blocks (download)."""
	percent, text = battery or (None, '')
	if percent is None or (text and text != 'On battery'):
		return ''
	return life_text(power_for_device(device), percent, hz or 1000)


def power_for_device(device):
	"""The parsed power model for a devices.Device (downloaded once), or None. Blocks."""
	import depots
	path = depots.fetch_battery(device.model.key, device.usb_id.split(':')[-1])
	return parse_power(path) if path else None
