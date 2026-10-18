"""Small PipeWire helpers built on pw-dump, pw-link and wpctl."""
import json
import subprocess

VIRTUAL_MIC = 'bluevoice_mic'
DSP = 'bluevoice_dsp'


def dump():
	try:
		out = subprocess.run(['pw-dump'], capture_output=True, text=True, timeout=5).stdout
		return json.loads(out or '[]')
	except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
		return []


def _props(obj):
	return obj.get('info', {}).get('props', {})


def sources(objs=None):
	"""Real microphones: [{'id', 'name', 'description'}], excluding our own virtual mic."""
	out = []
	for o in objs if objs is not None else dump():
		p = _props(o)
		if o.get('type', '').endswith('Node') and p.get('media.class') == 'Audio/Source' \
				and p.get('node.name') != VIRTUAL_MIC:
			out.append({'id': o['id'], 'name': p.get('node.name', ''),
			            'description': p.get('node.description') or p.get('node.nick') or p.get('node.name', '')})
	return out


def default_source_name():
	try:
		out = subprocess.run(['wpctl', 'inspect', '@DEFAULT_AUDIO_SOURCE@'], capture_output=True, text=True,
		                     timeout=5).stdout
	except (OSError, subprocess.TimeoutExpired):
		return None
	for line in out.splitlines():
		line = line.strip().lstrip('* ')
		if line.startswith('node.name = '):
			return line.split('=', 1)[1].strip().strip('"')
	return None


def is_pro_x(src):
	text = f"{src['name']} {src['description']}".lower().replace('_', ' ')
	return 'pro x' in text or 'prox' in text or 'g pro' in text


def pick_input(wanted, objs=None):
	"""The source to process: the configured one if present, else a G Pro X, else the default mic."""
	srcs = sources(objs)
	if wanted and wanted != 'auto':
		for s in srcs:
			if s['name'] == wanted:
				return s
		return None  # the chosen mic is unplugged; wait for it rather than grabbing another
	for s in srcs:
		if is_pro_x(s):
			return s
	default = default_source_name()
	for s in srcs:
		if s['name'] == default:
			return s
	return srcs[0] if srcs else None


def node_id(name, objs=None):
	for o in objs if objs is not None else dump():
		if o.get('type', '').endswith('Node') and _props(o).get('node.name') == name:
			return o['id']
	return None


def ports(node_name, direction, objs=None):
	"""Port names ('node:port') of a node, in id order. direction: 'in' or 'out'."""
	objs = objs if objs is not None else dump()
	nid = node_id(node_name, objs)
	found = []
	for o in objs:
		if not o.get('type', '').endswith('Port'):
			continue
		p = _props(o)
		if p.get('node.id') == nid and p.get('port.direction') == direction:
			found.append((o['id'], p.get('audio.channel', ''), f"{node_name}:{p.get('port.name')}"))
	found.sort()
	return found


def capture_port(node_name, objs=None):
	"""The port to take a mono signal from: MONO if there is one, else front-left, else the first."""
	outs = ports(node_name, 'out', objs)
	for wanted in ('MONO', 'FL'):
		for _, channel, name in outs:
			if channel == wanted:
				return name
	return outs[0][2] if outs else None


def links_into(port_full_name, objs=None):
	"""Output ports currently linked into the given input port."""
	objs = objs if objs is not None else dump()
	port_ids = {}
	for o in objs:
		if o.get('type', '').endswith('Port'):
			p = _props(o)
			nid = p.get('node.id')
			node = next((_props(n).get('node.name') for n in objs
			             if n.get('id') == nid and n.get('type', '').endswith('Node')), None)
			port_ids[o['id']] = f"{node}:{p.get('port.name')}"
	target = next((i for i, n in port_ids.items() if n == port_full_name), None)
	found = []
	for o in objs:
		if o.get('type', '').endswith('Link'):
			info = o.get('info', {})
			if info.get('input-port-id') == target:
				found.append(port_ids.get(info.get('output-port-id')))
	return [f for f in found if f]


def link(out_port, in_port):
	return subprocess.run(['pw-link', out_port, in_port], capture_output=True, text=True).returncode == 0


def unlink(out_port, in_port):
	subprocess.run(['pw-link', '-d', out_port, in_port], capture_output=True, text=True)


def set_default_source(node_name):
	nid = node_id(node_name)
	if nid is not None:
		subprocess.run(['wpctl', 'set-default', str(nid)], capture_output=True)
