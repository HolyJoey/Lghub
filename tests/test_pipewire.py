import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import eq  # noqa: E402
import pw  # noqa: E402
import surround  # noqa: E402

HEADSET = 'alsa_output.usb-Logitech_PRO_X'
SPEAKERS = 'alsa_output.pci-speakers'
HEADSET_MIC = 'alsa_input.usb-Logitech_PRO_X'
LAPTOP_MIC = 'alsa_input.pci-mic'


def node(nid, name, media_class, description=''):
	props = {pw.NODE_NAME: name, 'media.class': media_class}
	if description:
		props['node.description'] = description
	return {'id': nid, 'type': 'PipeWire:Interface:Node', 'info': {'props': props}}


def port(pid, node_id, name, direction, channel=''):
	return {'id': pid, 'type': 'PipeWire:Interface:Port',
	        'info': {'props': {'node.id': node_id, 'port.name': name, 'port.direction': direction,
	                           'audio.channel': channel}}}


def link(out_port, in_port, out_node, in_node):
	return {'id': 900 + out_port, 'type': 'PipeWire:Interface:Link',
	        'info': {'output-port-id': out_port, 'input-port-id': in_port,
	                 'output-node-id': out_node, 'input-node-id': in_node}}


def graph(playing=False, dsp_linked=False):
	"""A headset, speakers, two mics, the virtual mic and our surround / EQ nodes."""
	objs = [node(30, HEADSET, 'Audio/Sink', 'PRO X Analog'), node(31, SPEAKERS, 'Audio/Sink', 'Speakers'),
	        node(40, HEADSET_MIC, 'Audio/Source', 'PRO X Mic'), node(41, LAPTOP_MIC, 'Audio/Source', 'Laptop Mic'),
	        node(50, pw.VIRTUAL_MIC, 'Audio/Source', 'Blue VO!CE'), node(60, eq.SINK, 'Audio/Sink'),
	        node(70, surround.SINK, 'Audio/Sink'), node(80, surround.DSP, 'Audio/Filter'),
	        node(90, 'firefox', 'Stream/Output/Audio'),
	        port(300, 30, 'playback_FL', 'in', 'FL'), port(301, 30, 'playback_FR', 'in', 'FR'),
	        port(401, 40, 'capture_FR', 'out', 'FR'), port(400, 40, 'capture_FL', 'out', 'FL'),
	        port(410, 41, 'capture_MONO', 'out', 'MONO'),
	        port(700, 70, 'monitor_FL', 'out', 'FL'), port(800, 80, 'in_FL', 'in', 'FL'),
	        port(810, 80, 'out_FL', 'out', 'FL'), port(950, 90, 'output_FL', 'out', 'FL'),
	        port(701, 70, 'playback_FL', 'in', 'FL')]
	if playing:
		objs.append(link(950, 701, 90, 70))
	if dsp_linked:
		objs.append(link(700, 800, 70, 80))
	return objs


class PwTest(unittest.TestCase):
	def test_sources_skip_our_virtual_mic(self):
		names = [s['name'] for s in pw.sources(graph())]
		self.assertEqual(names, [HEADSET_MIC, LAPTOP_MIC])

	def test_pick_input(self):
		objs = graph()
		self.assertEqual(pw.pick_input(LAPTOP_MIC, objs)['name'], LAPTOP_MIC)
		self.assertIsNone(pw.pick_input('unplugged', objs))
		self.assertEqual(pw.pick_input('auto', objs)['name'], HEADSET_MIC)        # the Blue VO!CE headset
		without = [o for o in objs if o['id'] != 40]
		with mock.patch.object(pw, 'default_source_name', return_value=LAPTOP_MIC):
			self.assertEqual(pw.pick_input('auto', without)['name'], LAPTOP_MIC)
		with mock.patch.object(pw, 'default_source_name', return_value=None):
			self.assertEqual(pw.pick_input(None, without)['name'], LAPTOP_MIC)
			self.assertIsNone(pw.pick_input(None, []))

	def test_ports_and_capture_port(self):
		objs = graph()
		self.assertEqual([p[2] for p in pw.ports(HEADSET_MIC, 'out', objs)],
		                 [f'{HEADSET_MIC}:capture_FL', f'{HEADSET_MIC}:capture_FR'])
		self.assertEqual(pw.capture_port(HEADSET_MIC, objs), f'{HEADSET_MIC}:capture_FL')
		self.assertEqual(pw.capture_port(LAPTOP_MIC, objs), f'{LAPTOP_MIC}:capture_MONO')
		self.assertIsNone(pw.capture_port('missing', objs))

	def test_links(self):
		objs = graph(playing=True, dsp_linked=True)
		self.assertEqual(pw.links_into(f'{surround.DSP}:in_FL', objs), [f'{surround.SINK}:monitor_FL'])
		self.assertEqual(pw.links_into_node(surround.SINK, objs), 1)
		self.assertEqual(pw.links_out_of(surround.SINK, objs), 1)
		self.assertEqual(pw.links_into_node(HEADSET, objs), 0)

	def test_commands(self):
		inspect = 'id 41, type PipeWire:Interface:Node\n  * node.name = "alsa_input.pci-mic"\n'
		with mock.patch('subprocess.run', return_value=mock.Mock(stdout=inspect, returncode=0)) as run:
			self.assertEqual(pw.default_source_name(), LAPTOP_MIC)
			self.assertTrue(pw.link('a:out', 'b:in'))
			pw.unlink('a:out', 'b:in')
			run.assert_called_with(['pw-link', '-d', 'a:out', 'b:in'], capture_output=True, text=True)
			self.assertTrue(pw.set_volume(LAPTOP_MIC, 1.5, graph()))
			run.assert_called_with(['wpctl', 'set-volume', '41', '1.000'], capture_output=True)
			self.assertFalse(pw.set_volume('missing', 0.5, graph()))
		with mock.patch('subprocess.run', side_effect=OSError):
			self.assertIsNone(pw.default_source_name())
			self.assertEqual(pw.dump(), [])
		with mock.patch('subprocess.run', return_value=mock.Mock(stdout='[{"id": 1}]')):
			self.assertEqual(pw.dump(), [{'id': 1}])


class FakeProc:
	def __init__(self, *_a, **_k):
		self.terminated = False

	def poll(self):
		return 0 if self.terminated else None

	def terminate(self):
		self.terminated = True

	def wait(self, timeout=None):
		return 0


class RunnerTest(unittest.TestCase):
	def setUp(self):
		tmp = tempfile.mkdtemp()
		patches = [mock.patch('store.RUN_DIR', tmp), mock.patch.object(eq, 'CONF_FILE', os.path.join(tmp, 'eq.conf')),
		           mock.patch.object(surround, 'PARAMS_FILE', os.path.join(tmp, 'surround.params')),
		           mock.patch('subprocess.Popen', FakeProc), mock.patch('subprocess.run'),
		           mock.patch.object(eq, 'load', return_value={'enabled': False}),
		           mock.patch.object(surround, 'available', return_value=True)]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_eq_sinks_and_target(self):
		objs = graph()
		self.assertEqual([s['name'] for s in eq.sinks(objs)], [HEADSET, SPEAKERS])
		self.assertEqual(eq.pick_target('auto', objs)['name'], HEADSET)
		self.assertEqual(eq.pick_target(SPEAKERS, objs)['name'], SPEAKERS)
		self.assertIsNone(eq.pick_target('missing', objs))

	def test_eq_runner_starts_sets_gains_defaults_and_stops(self):
		r = eq.Runner()
		r.settings = {'enabled': True, 'target': 'auto', 'gains': [1.0] * len(eq.BANDS), 'make_default': True}
		objs = graph()
		r.check(objs)
		self.assertEqual(r.target, HEADSET)
		with open(eq.CONF_FILE) as f:
			self.assertIn(HEADSET, f.read())
		r.settings['gains'] = [2.0] * len(eq.BANDS)
		subprocess.run.return_value = mock.Mock(returncode=0)
		r.check(objs)
		self.assertEqual(r.gains, [2.0] * len(eq.BANDS))
		subprocess.run.assert_called_with(['wpctl', 'set-default', '60'], capture_output=True)
		self.assertTrue(r.defaulted)
		r.settings['enabled'] = False
		r.check(objs)
		self.assertIsNone(r.proc)
		subprocess.run.assert_called_with(['wpctl', 'set-default', '30'], capture_output=True)   # back to the headset

	def test_set_gains_needs_the_node(self):
		self.assertFalse(eq.set_gains([0.0], []))

	def test_surround_links_while_playing_and_unlinks_after(self):
		r = surround.Runner()
		r.settings = {**surround.default_settings(), 'enabled': True, 'make_default': False}
		r.check(graph())
		self.assertEqual(r.headset, HEADSET)
		with mock.patch.object(surround.pw, 'link') as link_, mock.patch.object(surround.pw, 'unlink') as unlink_:
			r.check(graph(playing=True))
			link_.assert_any_call(f'{surround.SINK}:monitor_FL', f'{surround.DSP}:in_FL')
			link_.assert_any_call(f'{surround.DSP}:out_FL', f'{HEADSET}:playback_FL')
			r.last_playing -= surround.IDLE_GRACE + 1
			r.check(graph(dsp_linked=True))
			unlink_.assert_any_call(f'{surround.SINK}:monitor_FL', f'{surround.DSP}:in_FL')

	def test_surround_off_without_headset(self):
		r = surround.Runner()
		r.settings = {**surround.default_settings(), 'enabled': True}
		r.check([o for o in graph() if o['id'] != 30])
		self.assertIsNone(r.proc)

	def test_surround_params_include_eq(self):
		text = surround.params_text(surround.default_settings(), {'enabled': True, 'gains': [1.5, -2.0]})
		self.assertIn('room 1', text)
		self.assertIn('eq 1\neq_1 1.50\neq_2 -2.00', text)


if __name__ == '__main__':
	unittest.main()
