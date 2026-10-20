"""The screen for the screen sampler on desktops without grim (GNOME, KDE): Wayland's screen-sharing
portal (org.freedesktop.portal.ScreenCast) hands out a PipeWire video stream of one monitor, which
GStreamer's pipewiresrc reads at a small size. The portal asks once; its restore token (kept in
config.json "screencast_token") lets later sessions start without asking again (portal v4+;
Hyprland's picker only gives one when its "Allow a restore token" box is ticked).
All of this is ours: G HUB samples the Windows desktop directly.
"""
import itertools

from gi.repository import Gio, GLib

import store

PORTAL, PATH = 'org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop'
CAST, REQUEST = 'org.freedesktop.portal.ScreenCast', 'org.freedesktop.portal.Request'
MONITOR = 1                   # source types: 1 monitor, 2 window
PERSIST_UNTIL_REVOKED = 2
WIDTH, HEIGHT = 160, 90       # the picture the sampler averages (ours: plenty for region colours)
TIMEOUT_S = 120               # the user may take a while in the portal's dialog
_tokens = itertools.count(1)


class PortalError(OSError):
	pass


class Portal:
	"""One ScreenCast session; call() runs one portal request and waits for its answer."""

	def __init__(self):
		self.context = GLib.MainContext()
		self.context.push_thread_default()
		self.loop = GLib.MainLoop(self.context)
		self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
		self.sender = self.bus.get_unique_name()[1:].replace('.', '_')

	def close(self):
		self.context.pop_thread_default()

	def call(self, method, args, signature):
		"""The results dict of a portal request (the Request object's Response signal)."""
		token = f'lghub{next(_tokens)}'
		handle = f'/org/freedesktop/portal/desktop/request/{self.sender}/{token}'
		answer = {}

		def response(_c, _s, _p, _i, _sig, params):
			answer['code'], answer['results'] = params.unpack()
			self.loop.quit()

		sub = self.bus.signal_subscribe(PORTAL, REQUEST, 'Response', handle, None, Gio.DBusSignalFlags.NONE, response)
		args[-1]['handle_token'] = GLib.Variant('s', token)
		try:
			self.bus.call_sync(PORTAL, PATH, CAST, method, GLib.Variant(signature, tuple(args)), None,
			                   Gio.DBusCallFlags.NONE, -1, None)
			timer = GLib.timeout_source_new_seconds(TIMEOUT_S)
			timer.set_callback(lambda *_: self.loop.quit())
			timer.attach(self.context)
			self.loop.run()
			timer.destroy()
		except GLib.Error as e:
			raise PortalError(e.message) from e
		finally:
			self.bus.signal_unsubscribe(sub)
		if answer.get('code') != 0:
			raise PortalError(f'screen sharing {method} refused or cancelled')
		return answer['results']

	def start(self):
		"""(PipeWire fd, node id) of a monitor stream."""
		session = self.call('CreateSession', [{'session_handle_token': GLib.Variant('s', 'lghubsession')}],
		                    '(a{sv})')['session_handle']
		options = {'types': GLib.Variant('u', MONITOR), 'multiple': GLib.Variant('b', False),
		           'persist_mode': GLib.Variant('u', PERSIST_UNTIL_REVOKED)}
		saved = store.load_config().get('screencast_token')
		if saved:
			options['restore_token'] = GLib.Variant('s', saved)
		self.call('SelectSources', [session, options], '(oa{sv})')
		started = self.call('Start', [session, '', {}], '(osa{sv})')
		if started.get('restore_token'):
			cfg = store.load_config()
			cfg['screencast_token'] = started['restore_token']
			store.save_config(cfg)
		streams = started.get('streams') or []
		if not streams:
			raise PortalError('the portal gave no screen')
		reply, fds = self.bus.call_with_unix_fd_list_sync(
			PORTAL, PATH, CAST, 'OpenPipeWireRemote', GLib.Variant('(oa{sv})', (session, {})), None,
			Gio.DBusCallFlags.NONE, -1, None, None)
		return fds.get(reply.unpack()[0]), streams[0][0]


def pipeline_text(fd, node):
	return (f'pipewiresrc fd={fd} path={node} always-copy=true do-timestamp=true ! videoconvert ! videoscale ! '
	        f'video/x-raw,format=RGB,width={WIDTH},height={HEIGHT} ! appsink name=out max-buffers=1 drop=true sync=false')


def unpad(data, width, height, stride):
	"""RGB rows without the padding GStreamer adds to keep each row a multiple of 4 bytes."""
	if stride == width * 3:
		return data
	return b''.join(data[y * stride:y * stride + width * 3] for y in range(height))


class Screen:
	"""grab() -> (width, height, RGB bytes) of the latest frame, like parse_ppm gives for grim."""

	def __init__(self):
		import gi
		gi.require_version('Gst', '1.0')
		from gi.repository import Gst
		Gst.init(None)
		try:
			self.portal = Portal()
			fd, node = self.portal.start()
			self.pipeline = Gst.parse_launch(pipeline_text(fd, node))
		except GLib.Error as e:
			raise PortalError(e.message) from e
		self.sink = self.pipeline.get_by_name('out')
		self.pipeline.set_state(Gst.State.PLAYING)
		self.gst = Gst

	def grab(self, timeout_s=2.0):
		sample = self.sink.emit('try-pull-sample', int(timeout_s * self.gst.SECOND))
		if sample is None:
			raise OSError('no picture from the screen-sharing stream')
		caps = sample.get_caps().get_structure(0)
		buf = sample.get_buffer()
		ok, info = buf.map(self.gst.MapFlags.READ)
		if not ok:
			raise OSError('can’t read the picture')
		try:
			width, height = caps.get_value('width'), caps.get_value('height')
			stride = len(info.data) // height
			data = bytes(info.data)
		finally:
			buf.unmap(info)
		return width, height, unpad(data, width, height, stride)

	def close(self):
		self.pipeline.set_state(self.gst.State.NULL)
		self.portal.close()
