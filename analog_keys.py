"""Names for the analog keyboards' per-key settings. The onboard profile keeps them by control index
(CIDX: a key's place in the keyboard's 0x1B10 control list, G HUB's CidMap); G HUB's picture layout
(metadata.json inputRegions) places each control id (CID) on the keyboard, and its key zones place
each HID key. Matching the two places names every CIDX (the matching is ours)."""
import json

import depots
import mouse
import perkey


def _centre(rendering):
	box = perkey._box(rendering)
	return (box[0] + box[2] / 2, box[1] + box[3] / 2) if box else None


def cid_places(model):
	"""{CID: (x, y)} from the model's picture layout."""
	try:
		with open(depots.metadata_path(model)) as f:
			image = json.load(f)['images'][0]
	except (OSError, ValueError, KeyError, IndexError):
		return {}
	out = {}
	for region in image.get('inputRegions', []):
		place = next((c for c in map(_centre, region.get('renderings', [])) if c), None)
		for item in region.get('inputs', []):
			if place and 'cid' in item:
				out[item['cid']] = place
	return out


def cid_usages(model):
	"""{CID: HID usage}: each control matched to the HID key drawn where it is."""
	layout = perkey.load_layout(model)
	if not layout:
		return {}
	keys = [((x + w / 2, y + h / 2), k) for g, k, x, y, w, h in layout[2] if g == 'PERKEY_KEYBOARD']

	def nearest(place):
		cx, cy = place
		return min(keys, key=lambda e: (e[0][0] - cx) ** 2 + (e[0][1] - cy) ** 2)[1]
	if not keys:
		return {}
	return {cid: nearest(place) for cid, place in cid_places(model).items()}


def cid_names(model):
	"""{CID: key name}: each control named after the HID key drawn where it is."""
	return {cid: mouse.KEY_NAMES.get(usage, f'Key {usage}') for cid, usage in cid_usages(model).items()}


def per_key_rows(profile, cids, model):
	"""[(key name, actuation mm or None, rapid-trigger mm or None)] for the keys that have their own
	values in an analog profile (device_settings.analog_profile); cids = the 0x1B10 list."""
	names = cid_names(model)
	keys, rapid = profile.get('keys', {}), profile.get('rapid', {})
	rows = []
	for cidx in sorted(set(keys) | set(rapid)):
		cid = cids[cidx] if cidx < len(cids) else None
		rows.append((names.get(cid, f'Control {cidx}'), keys.get(cidx), rapid.get(cidx)))
	return rows
