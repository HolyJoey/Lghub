import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import tray  # noqa: E402


class TrayMenuTest(unittest.TestCase):
	def test_items(self):
		items = tray.menu_items([('G502 HERO', None), ('G733', (35, 'Charging'))],
		                        [('voice', 'Blue VO!CE', True, None), ('eq', 'Equalizer', False, None)])
		labels = [p.get('label') for _i, p in items]
		self.assertEqual(labels, ['G502 HERO', 'G733 · 35 % (charging)', None, 'Blue VO!CE', 'Equalizer', None,
		                          'Open Lghub', 'Quit Lghub'])
		self.assertEqual(dict(items)[10]['toggle-state'], 1)
		self.assertEqual(dict(items)[11]['toggle-state'], 0)

	def test_no_devices(self):
		items = tray.menu_items([], [])
		self.assertEqual(items[0][1]['label'], 'No Logitech device connected')


class FakeInvocation:
	def __init__(self):
		self.value = 'unset'

	def return_value(self, value):
		self.value = value


class TrayBusTest(unittest.TestCase):
	def setUp(self):
		self.flipped = []
		switches = [('eq', 'Equalizer', False, lambda: self.flipped.append('eq'))]
		patcher = mock.patch.object(tray, '_switches', return_value=switches)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.tray = tray.Tray(lambda: [('G733', (35, 'On battery'))])
		self.tray.conn = mock.Mock()
		self.tray._rebuild()

	def call(self, method, params=None):
		from gi.repository import GLib
		inv = FakeInvocation()
		args = GLib.Variant(*params) if params else None
		self.tray._menu_call(None, None, None, None, method, args, inv)
		return inv.value

	def test_layout_and_properties(self):
		layout = self.call('GetLayout', ('(iias)', (0, -1, []))).unpack()
		self.assertEqual(layout[0], self.tray.revision)
		labels = [child[1].get('label') for child in layout[1][2]]
		self.assertIn('G733 · 35 %', labels)
		self.assertIn('Equalizer', labels)
		rows = self.call('GetGroupProperties', ('(aias)', ([1], []))).unpack()[0]
		self.assertEqual(rows, [(1, {'label': 'Open Lghub'})])
		self.assertIn(self.tray._item_get(None, None, None, None, 'IconName').unpack(), ('lghub', 'lghub-logo'))
		self.assertEqual(self.call('GetProperty', ('(is)', (1, 'label'))).unpack()[0], 'Open Lghub')
		self.assertEqual(self.call('AboutToShow', ('(i)', (0,))).unpack(), (False,))
		self.assertEqual(self.call('AboutToShowGroup', ('(ai)', ([],))).unpack(), ([], []))
		self.assertEqual(self.tray._menu_get(None, None, None, None, 'Version').unpack(), 3)
		self.assertIn('G733', self.tray._item_get(None, None, None, None, 'ToolTip').unpack()[3])
		self.assertEqual(self.tray._item_get(None, None, None, None, 'Menu').unpack(), tray.MENU_PATH)

	def test_clicks(self):
		from gi.repository import GLib
		before = self.tray.revision
		self.call('Event', ('(isvu)', (10, 'clicked', GLib.Variant('s', ''), 0)))
		self.assertEqual(self.flipped, ['eq'])
		self.assertGreater(self.tray.revision, before)
		self.tray.conn.emit_signal.assert_called()
		with mock.patch.object(tray, 'open_app') as open_app:
			self.call('EventGroup', ('(a(isvu))', ([(1, 'clicked', GLib.Variant('s', ''), 0)],)))
			inv = FakeInvocation()
			self.tray._item_call(None, None, None, None, 'Activate', None, inv)
		self.assertEqual(open_app.call_count, 2)

	def test_open_app_falls_back_to_the_script(self):
		with mock.patch('subprocess.Popen', side_effect=[OSError, mock.Mock()]) as popen:
			tray.open_app()
		self.assertEqual(popen.call_args_list[1].args[0][0], 'python3')

	def test_icon_follows_the_installer(self):
		with tempfile.TemporaryDirectory() as d:
			self.assertEqual(tray.icon_name(d), 'lghub-logo')
			os.makedirs(os.path.join(d, 'hicolor', '256x256', 'apps'))
			open(os.path.join(d, 'hicolor', '256x256', 'apps', 'lghub.png'), 'w').close()
			self.assertEqual(tray.icon_name(d), 'lghub')

	def test_quit_closes_the_window_and_stops_the_service(self):
		from gi.repository import GLib
		bus = mock.Mock()
		with mock.patch('service.stop') as stop:
			tray.quit_all(bus)
			bus.call_sync.side_effect = GLib.Error('not running')
			tray.quit_all(bus)
		self.assertEqual(bus.call_sync.call_args.args[3], 'Activate')
		self.assertEqual(stop.call_count, 2)
		with mock.patch.object(tray, 'quit_all') as quit_all:
			self.tray._clicked(tray.QUIT)
			threading.Event().wait(0.05)                       # it runs on its own thread
		quit_all.assert_called_once()

	def test_switches_flip_settings(self):
		mock.patch.stopall()
		saved = {}
		with mock.patch('store.load_config', return_value={'enabled': True}), \
				mock.patch('store.save_config', lambda cfg: saved.update(voice=cfg['enabled'])), \
				mock.patch('eq.load', return_value={'enabled': False}), \
				mock.patch('eq.save', lambda s: saved.update(eq=s['enabled'])), \
				mock.patch('surround.load', return_value={'enabled': True}), \
				mock.patch('surround.save', lambda s: saved.update(surround=s['enabled'])):
			for _key, _text, _on, flip in tray._switches():
				flip()
		self.assertEqual(saved, {'voice': False, 'eq': True, 'surround': False})


if __name__ == '__main__':
	unittest.main()
