"""The surround engine's runner (surround.Runner): the link order that keeps the DSP from stalling, the
idle grace before unlinking, starting / stopping the bridge, and the default output it restores."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import surround  # noqa: E402

HEADSET = {'name': 'alsa_output.usb-Logitech_PRO_X_000000-00.analog-stereo', 'description': 'PRO X'}


class Links:
	"""A fake PipeWire link table for pw.links_into / links_into_node / link / unlink."""

	def __init__(self, playing=0):
		self.links, self.log, self.playing = set(), [], playing

	def links_into(self, dst, _objs=None):
		return [s for s, d in self.links if d == dst]

	def links_into_node(self, _node, _objs=None):
		return self.playing

	def link(self, src, dst):
		self.links.add((src, dst))
		self.log.append(('link', src, dst))

	def unlink(self, src, dst):
		self.links.discard((src, dst))
		self.log.append(('unlink', src, dst))


class RunnerLinkTest(unittest.TestCase):
	def setUp(self):
		self.pw = Links(playing=1)
		patches = [mock.patch.object(surround.pw, name, getattr(self.pw, name))
		           for name in ('links_into', 'links_into_node', 'link', 'unlink')]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		self.runner = surround.Runner()

	def test_outputs_link_before_inputs_and_unlink_after(self):
		self.runner._link([], HEADSET)
		kinds = [dst.startswith(surround.DSP) for _op, _src, dst in self.pw.log]
		self.assertEqual(kinds, [False, False] + [True] * len(surround.CHANNELS))   # DSP -> headset first
		self.pw.log.clear()
		self.runner._link([], HEADSET)
		self.assertEqual(self.pw.log, [])                                         # nothing twice
		self.pw.playing = 0
		self.runner.last_playing -= surround.IDLE_GRACE + 1
		self.runner._link([], HEADSET)
		kinds = [dst.startswith(surround.DSP) for _op, _src, dst in self.pw.log]
		self.assertEqual(kinds, [True] * len(surround.CHANNELS) + [False, False])   # inputs first on the way out
		self.assertEqual(self.pw.links, set())

	def test_grace_keeps_links_and_schedules_the_unlink(self):
		self.runner._link([], HEADSET)
		self.pw.playing = 0
		self.runner._link([], HEADSET)
		self.assertTrue(self.pw.links)
		self.assertGreater(self.runner.next_check, self.runner.last_playing + surround.IDLE_GRACE)


class RunnerLifecycleTest(unittest.TestCase):
	def test_start_check_and_stop(self):
		import store
		with tempfile.TemporaryDirectory() as tmp, mock.patch.object(store, 'RUN_DIR', tmp), \
		     mock.patch.object(surround, 'PARAMS_FILE', os.path.join(tmp, 'params')), \
		     mock.patch.object(surround, 'available', return_value=True), \
		     mock.patch.object(surround, 'pw_headset', return_value=HEADSET), \
		     mock.patch.object(surround.subprocess, 'Popen') as popen, \
		     mock.patch.object(surround.subprocess, 'run') as run, \
		     mock.patch.object(surround.pw, 'node_id', return_value=42), \
		     mock.patch.object(surround.Runner, '_link') as link:
			popen.return_value.poll.return_value = None
			r = surround.Runner()
			r.settings = {**surround.default_settings(), 'enabled': True, 'make_default': True}
			r.check([])                                    # starts the bridge for the headset
			self.assertTrue(popen.called)
			self.assertEqual(r.headset, HEADSET['name'])
			self.assertTrue(os.path.exists(os.path.join(tmp, 'params')))
			r.check([])                                    # links and makes it the default output
			self.assertTrue(link.called)
			self.assertTrue(r.defaulted)
			run.reset_mock()
			r.stop([])
			self.assertEqual(run.call_args[0][0], ['wpctl', 'set-default', '42'])   # the default goes back
			self.assertIsNone(r.proc)
			r.settings['enabled'] = False
			r.check([])                                    # off: nothing starts
			self.assertEqual(popen.call_count, 1)

	def test_bridge_that_does_not_start(self):
		with mock.patch.object(surround.subprocess, 'Popen', side_effect=OSError('missing')), \
		     mock.patch.object(surround.Runner, '_write_params'):
			r = surround.Runner()
			r._start(HEADSET)
		self.assertIsNone(r.proc)
		self.assertIsNone(r.headset)


if __name__ == '__main__':
	unittest.main()
