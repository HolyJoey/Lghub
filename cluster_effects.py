"""The newer headsets' stored lighting effects (HID++ feature 0x0621 over the Centurion transport), as
G HUB reads and sets them (re/notes/centurion.txt):

- fn 0 getInfo: [byte 0, n, n x 2 bytes], one pair per cluster (a cluster is a lighting zone).
- fn 1 getRGBClusterInfo [cluster]: [n, n x (effect id u16 BE, byte, capability bits)].
- fn 2 getRGBClusterEffect [cluster] / fn 3 setRGBClusterEffect: [cluster, effect id u16 BE, params]
  (G HUB sends 10 bytes, zero-padded).
- Effect ids and params, from G HUB's conversion to its firmware_lighting effects (0x1422770c0) and
  its request / reply packing (0x141f2c840 / 0x141f341e0): 0 fixed [r, g, b] (black = off),
  1 colour cycle [intensity %, period ms u16 BE, saturation], 2 colour wave [the same, direction],
  3 breathing [r, g, b, intensity %, period ms u16 BE], 4 signature [r, g, b, r2, g2, b2,
  intensity %], 5 custom (no params; G HUB doesn't set it this way)."""
INFO, CLUSTER_INFO, GET, SET = 0, 1, 2, 3
FEATURE = 0x0621
FIXED, CYCLE, WAVE, BREATHING, SIGNATURE, CUSTOM = range(6)
NAMES = {FIXED: 'Fixed', CYCLE: 'Colour cycle', WAVE: 'Colour wave', BREATHING: 'Breathing',
         SIGNATURE: 'Signature', CUSTOM: 'Custom'}
SETTABLE = (FIXED, CYCLE, WAVE, BREATHING, SIGNATURE)
# Wave directions on the wire, G HUB's names (HORIZONTAL, VERTICAL, REVERSE_HORIZONTAL, REVERSE_VERTICAL)
DIRECTIONS = ('Horizontal', 'Vertical', 'Reverse horizontal', 'Reverse vertical')
REQUEST_SIZE = 10
DEFAULTS = {'color': (0, 0, 0), 'color2': (0, 0, 0), 'period': 5000, 'intensity': 100, 'saturation': 100,
            'direction': 0}      # ours: G HUB fills these from the card


def clusters(dev):
	"""The headset's cluster indexes."""
	return list(range(dev.call(FEATURE, INFO)[1]))


def cluster_effects(dev, cluster):
	"""The effect ids this cluster can keep."""
	r = dev.call(FEATURE, CLUSTER_INFO, bytes([cluster]))
	return [(r[1 + 4 * i] << 8) | r[2 + 4 * i] for i in range(r[0]) if 5 + 4 * i <= len(r)]


def decode(r):
	"""(effect id, params) from a getRGBClusterEffect reply."""
	eid, p = (r[1] << 8) | r[2], r[3:]
	if eid == FIXED:
		return eid, {'color': tuple(p[0:3])}
	if eid in (CYCLE, WAVE):
		out = {'intensity': p[0], 'period': (p[1] << 8) | p[2], 'saturation': p[3]}
		if eid == WAVE:
			out['direction'] = p[4]
		return eid, out
	if eid == BREATHING:
		return eid, {'color': tuple(p[0:3]), 'intensity': p[3], 'period': (p[4] << 8) | p[5]}
	if eid == SIGNATURE:
		return eid, {'color': tuple(p[0:3]), 'color2': tuple(p[3:6]), 'intensity': p[6]}
	return eid, {}


def encode(cluster, eid, params):
	"""The setRGBClusterEffect request for this effect."""
	v = {**DEFAULTS, **params}
	period = max(0, min(0xFFFF, int(v['period'])))
	intensity = max(0, min(100, int(round(v['intensity']))))
	if eid == FIXED:
		body = list(v['color'])
	elif eid in (CYCLE, WAVE):
		body = [intensity, period >> 8, period & 0xFF, v['saturation']] + ([v['direction']] if eid == WAVE else [])
	elif eid == BREATHING:
		body = [*v['color'], intensity, period >> 8, period & 0xFF]
	elif eid == SIGNATURE:
		body = [*v['color'], *v['color2'], intensity]
	else:
		raise ValueError(f'G HUB doesn’t set effect {eid} this way')
	out = bytes([cluster, eid >> 8, eid & 0xFF, *body])
	return out + bytes(REQUEST_SIZE - len(out))


def effect(dev, cluster):
	return decode(dev.call(FEATURE, GET, bytes([cluster])))


def set_effect(dev, cluster, eid, params):
	dev.call(FEATURE, SET, encode(cluster, eid, params))


def read(dev):
	"""[(cluster, [effect ids], (current effect id, params))]."""
	return [(c, cluster_effects(dev, c), effect(dev, c)) for c in clusters(dev)]
