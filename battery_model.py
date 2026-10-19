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
