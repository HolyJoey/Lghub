"""The background service's main loop: config, the Blue VO!CE bridge, links and status."""
import io
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import battery_watch  # noqa: E402
import engine  # noqa: E402
import pw  # noqa: E402
import store  # noqa: E402

RUNNERS = ('eq.Runner', 'webcam.Restorer', 'surround.Runner', 'hotplug.Watch', 'inputd.Manager',
           'profiles.Switcher', 'restore.Restorer', 'lightsync.Runner', 'battery_watch.Watch', 'osd.Watch',
           'tray.Tray')
MIC = {'id': 40, 'name': 'alsa_input.usb-Logitech_PRO_X', 'description': 'PRO X'}


class FakeBridge:
	pid = 4321

	def __init__(self, *args, **_kw):
		self.args = args[0] if args else []
		self.stderr = io.StringIO('meter -20.5 -18.0\nready\nmeter bad\nsomething else\n')
		self.returncode = None
		self.terminated = False

	def poll(self):
		return self.returncode

	def terminate(self):
		self.terminated = True

	def wait(self, timeout=None):
		return 0


class EngineTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp()
		files = {'RUN_DIR': self.tmp, 'CONFIG_DIR': self.tmp, 'CONFIG_FILE': os.path.join(self.tmp, 'config.json'),
		         'STATUS_FILE': os.path.join(self.tmp, 'status.json'), 'PARAMS_FILE': os.path.join(self.tmp, 'live.params'),
		         'BV2_PARAMS_FILE': os.path.join(self.tmp, 'bv2.params'), 'BRIDGE': os.path.join(self.tmp, 'bridge'),
		         'APO_DLL': os.path.join(self.tmp, 'apo.dll'), 'BV2_DLL': os.path.join(self.tmp, 'bv2.dll')}
		patches = [mock.patch.object(store, k, v) for k, v in files.items()]
		patches += [mock.patch(r) for r in RUNNERS]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		for f in ('BRIDGE', 'APO_DLL'):
			open(files[f], 'w').close()
		self.engine = engine.Engine()

	def test_config_files_written_once(self):
		e = self.engine
		e.reload_config()
		with open(store.PARAMS_FILE) as f:
			self.assertIn('micopt.enable', f.read())
		self.assertTrue(os.path.exists(store.BV2_PARAMS_FILE))
		before = os.stat(store.PARAMS_FILE).st_mtime_ns
		e.reload_config()
		self.assertEqual(os.stat(store.PARAMS_FILE).st_mtime_ns, before)
		cfg = store.load_config()
		cfg.update(input='other', enabled=False)
		store.save_config(cfg)
		e.config_mtime = -1
		e.last_link_check = 99.0
		e.reload_config()
		self.assertEqual(e.last_link_check, 0.0)                      # a new mic: relink now
		with open(store.PARAMS_FILE) as f:
			self.assertIn('micopt.enable 0', f.read())

	def test_bridge_start_output_and_restart(self):
		e = self.engine
		with mock.patch('subprocess.Popen', FakeBridge), mock.patch('threading.Thread'):
			e.check_bridge()
		self.assertEqual((e.kind, e.proc.args[2]), ('micopt', store.APO_DLL))
		e.read_bridge_output(e.proc)
		self.assertEqual((e.meter, e.ready), ((-20.5, -18.0), True))
		e.proc.returncode = 1
		e.check_bridge()                                               # died: wait, then retry
		self.assertIsNone(e.proc)
		self.assertIn('exit 1', e.last_error)
		self.assertEqual(e.backoff, 4.0)

	def test_missing_files_and_bv2(self):
		e = self.engine
		os.remove(store.APO_DLL)
		e.start_bridge()
		self.assertIn('apo.dll', e.last_error)
		self.assertIsNone(e.proc)
		open(store.BV2_DLL, 'w').close()
		e.input = {'name': 'yeti_x', 'description': 'Yeti X'}
		self.assertEqual(e.wanted_kind(), 'bv2')
		with mock.patch('subprocess.Popen', FakeBridge), mock.patch('threading.Thread'):
			e.start_bridge()
		self.assertIn('bv2', e.proc.args)
		e.stop_bridge()
		self.assertIsNone(e.proc)

	def test_link_events(self):
		e = self.engine
		e.on_link_change('= nothing\n')
		self.assertFalse(e.link_event.is_set())
		e.on_link_change(f'+ firefox:input_MONO -> {pw.VIRTUAL_MIC}:capture_MONO\n')
		self.assertTrue(e.link_event.is_set())
		e.link_event.clear()
		e.on_link_change('- app:out_FL -> lghub_surround:playback_FL\n')
		self.assertTrue(e.surround.wake)

	def check_links(self, listeners, linked_in=(), linked_out=False):
		e = self.engine
		e.kind = 'micopt'
		with mock.patch.object(pw, 'dump', return_value=[]), mock.patch.object(pw, 'pick_input', return_value=MIC), \
				mock.patch.object(pw, 'ports', return_value=[(1, 'MONO', f'{pw.VIRTUAL_MIC}:input_MONO')]), \
				mock.patch.object(pw, 'node_id', return_value=7), \
				mock.patch.object(pw, 'links_out_of', return_value=listeners), \
				mock.patch.object(pw, 'capture_port', return_value=f"{MIC['name']}:capture_FL"), \
				mock.patch.object(pw, 'links_into', side_effect=lambda port, _o=None: list(
					linked_in if port.endswith(':in') else ([f'{pw.DSP}:out'] if linked_out else []))), \
				mock.patch.object(pw, 'link') as link, mock.patch.object(pw, 'unlink') as unlink, \
				mock.patch.object(pw, 'set_default_source') as default:
			e.check_links()
		return link, unlink, default

	def test_mic_linked_only_while_an_app_records(self):
		e = self.engine
		e.config['make_default'] = True
		link, _unlink, default = self.check_links(listeners=1)
		self.assertTrue(e.listening)
		link.assert_any_call(f"{MIC['name']}:capture_FL", f'{pw.DSP}:in')
		link.assert_any_call(f'{pw.DSP}:out', f'{pw.VIRTUAL_MIC}:input_MONO')
		default.assert_called_once_with(pw.VIRTUAL_MIC)
		e.last_listener -= engine.IDLE_GRACE + 1
		_link, unlink, _d = self.check_links(listeners=0, linked_in=['other:capture_FL'], linked_out=True)
		self.assertFalse(e.listening)
		unlink.assert_any_call('other:capture_FL', f'{pw.DSP}:in')
		unlink.assert_any_call(f'{pw.DSP}:out', f'{pw.VIRTUAL_MIC}:input_MONO')

	def test_switching_dsp_restarts_the_bridge(self):
		e = self.engine
		open(store.BV2_DLL, 'w').close()
		e.kind, e.proc = 'micopt', FakeBridge()
		with mock.patch.object(pw, 'dump', return_value=[]), \
				mock.patch.object(pw, 'pick_input', return_value={'name': 'yeti', 'description': 'Yeti'}):
			e.check_links()
		self.assertIsNone(e.proc)

	def test_bv2_mic_gain(self):
		e = self.engine
		e.kind, e.input = 'bv2', MIC
		e.config['bv2_params'] = {engine.bv2_presets.MIC_GAIN: 0.7}
		with mock.patch.object(pw, 'set_volume', return_value=True) as set_volume:
			e.apply_mic_gain([])
			e.apply_mic_gain([])
		set_volume.assert_called_once_with(MIC['name'], 0.7, [])

	def test_publish_states(self):
		e = self.engine
		e.publish()
		self.assertEqual(store.read_status()['state'], 'error')
		e.proc = FakeBridge()
		e.publish()
		self.assertEqual(store.read_status()['state'], 'starting')
		e.ready, e.listening, e.meter = True, True, (-10.0, -12.0)
		e.publish()
		status = store.read_status()
		self.assertEqual((status['state'], status['meter_in']), ('running', -10.0))

	def test_rounds_call_what_is_due(self):
		e = self.engine
		e.proc = FakeBridge()
		e.sound_cards.changed.return_value = True
		with mock.patch.object(e, 'check_links') as check_links, mock.patch.object(pw, 'dump', return_value=[]):
			e.voice_round(1000.0)
			e.other_rounds(1000.0)
		check_links.assert_called_once()
		for runner in (e.eq, e.surround, e.webcams, e.inputs, e.restorer, e.lightsync, e.battery, e.osd):
			self.assertTrue(runner.check.called)
		e.tray.refresh.assert_called_once()

	def test_tray_devices(self):
		e = self.engine
		e.battery.readings = {'usb:1': ('G502', (80, 'On battery')), 'usb:2#1': ('G733', (40, 'Charging'))}
		corded = mock.Mock(id='usb:1', model=mock.Mock(type='mouse'))
		corded.name = 'G502'
		receiver = mock.Mock(id='usb:2', model=mock.Mock(type='receiver'))
		with mock.patch('devices.discover', return_value=[corded, receiver]):
			self.assertEqual(e.tray_devices(), [('G502', (80, 'On battery')), ('G733', (40, 'Charging'))])
		e.battery.readings = {}                       # plugged in, its mouse not read yet
		receiver.name = 'LIGHTSPEED Receiver'
		with mock.patch('devices.discover', return_value=[receiver]):
			self.assertEqual(e.tray_devices(), [('LIGHTSPEED Receiver', None)])

	def test_usb_hotplug_reads_devices_now(self):
		e = self.engine
		e.hid = mock.Mock()
		e.hid.changed.return_value = True
		e.battery.due.return_value = False
		e.other_rounds(1000.0)
		e.battery.check.assert_called_once_with(1000.0)
		e.tray.refresh.assert_called_once()
		self.assertEqual(e.battery.last, 1000.0 - battery_watch.CHECK_EVERY + engine.USB_SETTLE)   # and again soon

	def test_run_until_stopped(self):
		e = self.engine
		rounds = []

		def one_round(now):
			rounds.append(now)
			e.stop.set()

		with mock.patch.object(e, 'watch_links'), mock.patch.object(e, 'check_bridge'), \
				mock.patch.object(e, 'voice_round', one_round), mock.patch.object(e, 'other_rounds'), \
				mock.patch('signal.signal'):
			thread = threading.Thread(target=e.run)
			thread.start()
			thread.join(5)
		self.assertEqual(len(rounds), 1)
		self.assertEqual(store.read_status()['state'], 'stopped')
		e.tray.stop.assert_called_once()

	def test_watch_links_reads_pw_link(self):
		e = self.engine
		mon = mock.Mock(stdout=io.StringIO(f'+ a:out -> {pw.VIRTUAL_MIC}:input_MONO\n'))
		mon.kill.side_effect = e.stop.set                     # one pass
		with mock.patch('subprocess.Popen', return_value=mon):
			e.watch_links()
		self.assertTrue(e.link_event.is_set())
		mon.kill.assert_called_once()


if __name__ == '__main__':
	unittest.main()
