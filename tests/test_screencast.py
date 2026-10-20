import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import lightsync  # noqa: E402
import screencast  # noqa: E402


class ScreencastTest(unittest.TestCase):
	def test_unpad_drops_row_padding(self):
		rows = b'abc' + b'\0' + b'def' + b'\0'
		self.assertEqual(screencast.unpad(rows, 1, 2, 4), b'abcdef')
		self.assertEqual(screencast.unpad(b'abcdef', 2, 1, 6), b'abcdef')

	def test_pipeline_reads_small_rgb(self):
		text = screencast.pipeline_text(7, 42)
		self.assertIn('pipewiresrc fd=7 path=42', text)
		self.assertIn(f'format=RGB,width={screencast.WIDTH},height={screencast.HEIGHT}', text)

	@staticmethod
	def _sampler():
		return lightsync.ScreenSampler.__new__(lightsync.ScreenSampler)

	def test_grim_first(self):
		s = self._sampler()
		with mock.patch('subprocess.run') as run, mock.patch.object(lightsync, 'parse_ppm', return_value=(1, 1, b'abc')):
			grab = s._grabber()
			self.assertEqual(grab(), (1, 1, b'abc'))
		self.assertIsNone(s.screen)
		run.assert_called()

	def test_portal_when_grim_missing(self):
		s = self._sampler()
		screen = mock.Mock()
		with mock.patch('subprocess.run', side_effect=OSError('no grim')), \
				mock.patch.object(screencast, 'Screen', return_value=screen):
			grab = s._grabber()
		self.assertIs(grab, screen.grab)

	def test_neither(self):
		s = self._sampler()
		with mock.patch('subprocess.run', side_effect=OSError('no grim')), \
				mock.patch.object(screencast, 'Screen', side_effect=screencast.PortalError('cancelled')):
			self.assertIsNone(s._grabber())


class FakeBus:
	"""Answers portal requests the way xdg-desktop-portal does: a Response signal on the request."""

	def __init__(self, context, refuse=None):
		self.context, self.refuse, self.subs, self.calls = context, refuse, {}, []

	def get_unique_name(self):
		return ':1.42'

	def signal_subscribe(self, _sender, _iface, _member, path, _arg, _flags, callback):
		self.subs[path] = callback
		return path

	def signal_unsubscribe(self, sub):
		self.subs.pop(sub, None)

	def call_sync(self, _dest, _path, _iface, method, params, *_rest):
		from gi.repository import GLib
		args = params.unpack()
		self.calls.append((method, args))
		token = args[-1]['handle_token']
		path = f'/org/freedesktop/portal/desktop/request/1_42/{token}'
		results = {'CreateSession': {'session_handle': GLib.Variant('s', '/session/1')},
		           'SelectSources': {},
		           'Start': {'streams': GLib.Variant('a(ua{sv})', [(77, {})]),
		                     'restore_token': GLib.Variant('s', 'tok')}}[method]
		code = 1 if method == self.refuse else 0
		reply = GLib.Variant('(ua{sv})', (code, results))
		source = GLib.idle_source_new()
		source.set_callback(lambda *_: self.subs[path](None, None, None, None, None, reply) or False)
		source.attach(self.context)

	def call_with_unix_fd_list_sync(self, *_args):
		from gi.repository import GLib
		fds = mock.Mock()
		fds.get.return_value = 12
		return GLib.Variant('(h)', (0,)), fds


class PortalTest(unittest.TestCase):
	def start(self, refuse=None, config=None):
		saved = {}
		with mock.patch('gi.repository.Gio.bus_get_sync'), \
				mock.patch('store.load_config', return_value=dict(config or {})), \
				mock.patch('store.save_config', saved.update):
			portal = screencast.Portal()
			portal.bus = FakeBus(portal.context, refuse)
			portal.sender = '1_42'
			try:
				return portal.start(), portal.bus.calls, saved
			finally:
				portal.close()

	def test_handshake_gives_fd_and_node_and_keeps_the_token(self):
		(fd, node), calls, saved = self.start()
		self.assertEqual((fd, node), (12, 77))
		self.assertEqual([c[0] for c in calls], ['CreateSession', 'SelectSources', 'Start'])
		self.assertEqual(saved['screencast_token'], 'tok')
		options = calls[1][1][1]
		self.assertEqual((options['types'], options['persist_mode']), (screencast.MONITOR, 2))
		self.assertNotIn('restore_token', options)

	def test_saved_token_is_sent(self):
		_r, calls, _s = self.start(config={'screencast_token': 'old'})
		self.assertEqual(calls[1][1][1]['restore_token'], 'old')

	def test_cancelled(self):
		with self.assertRaises(screencast.PortalError):
			self.start(refuse='SelectSources')


if __name__ == '__main__':
	unittest.main()
