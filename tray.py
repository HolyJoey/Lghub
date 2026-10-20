"""A tray icon, like G HUB's system tray (logi.protocol.system_tray): each connected device with its
battery, quick switches (Blue VO!CE, equalizer, surround) and Open Lghub. Linux trays speak
StatusNotifierItem with a com.canonical.dbusmenu menu (waybar, KDE, GNOME's AppIndicator
extension); both are served here over D-Bus from the background service. Which switches are in
the menu is ours (G HUB's are per device).
"""
import os
import subprocess
import threading

from gi.repository import Gio, GLib

ITEM_PATH, MENU_PATH = '/StatusNotifierItem', '/MenuBar'
WATCHER = 'org.kde.StatusNotifierWatcher'
APP_ID, APP_PATH = 'dev.local.LghubBlueVoice', '/dev/local/LghubBlueVoice'   # the window (app.py)
ICONS = os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'), 'icons')
QUIT = 4

SNI_XML = '''<node><interface name="org.kde.StatusNotifierItem">
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="IconName" type="s" access="read"/><property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
<property name="Menu" type="o" access="read"/><property name="ItemIsMenu" type="b" access="read"/>
<property name="IconThemePath" type="s" access="read"/>
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
<signal name="NewToolTip"/><signal name="NewStatus"><arg type="s"/></signal>
</interface></node>'''

MENU_XML = '''<node><interface name="com.canonical.dbusmenu">
<property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/>
<property name="Status" type="s" access="read"/><property name="IconThemePath" type="as" access="read"/>
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
<arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/>
<arg type="a(ia{sv})" direction="out"/></method>
<method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
<arg type="u" direction="in"/></method>
<method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/>
<arg type="ai" direction="out"/></method>
<signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
</interface></node>'''


def open_app():
	"""Starts the Lghub window (the installed launcher, else app.py next to this file)."""
	for cmd in (['lghub'], ['python3', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')]):
		try:
			subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
			return
		except OSError:
			continue


def icon_name(icons=ICONS):
	"""The installer's icon: G HUB's logo when it was downloaded, else Lghub's own."""
	return 'lghub' if os.path.exists(os.path.join(icons, 'hicolor', '256x256', 'apps', 'lghub.png')) \
		else 'lghub-bluevoice'


def quit_all(bus):
	"""Close the Lghub window if it's open (its 'quit' action), then stop the background service
	(this process; it comes back at the next login or with the window)."""
	import service
	try:
		bus.call_sync(APP_ID, APP_PATH, 'org.gtk.Actions', 'Activate', GLib.Variant('(sava{sv})', ('quit', [], {})),
		              None, Gio.DBusCallFlags.NONE, 2000, None)
	except GLib.Error:
		pass                                     # the window isn't open
	service.stop()


def _switches():
	"""[(id, label, on, flip)] for the quick switches."""
	import eq
	import store
	import surround

	def flip_voice():
		cfg = store.load_config()
		cfg['enabled'] = not cfg.get('enabled', True)
		store.save_config(cfg)

	def flip(module):
		def run():
			s = module.load()
			s['enabled'] = not s.get('enabled', False)
			module.save(s)
		return run

	return [('voice', 'Blue VO!CE', store.load_config().get('enabled', True), flip_voice),
	        ('eq', 'Equalizer', eq.load().get('enabled', False), flip(eq)),
	        ('surround', 'Surround', surround.load().get('enabled', False), flip(surround))]


def menu_items(devices, switches):
	"""[(id, props)] of the menu: devices (with battery), switches, Open Lghub. devices =
	[(name, (percent or None, text) or None)]."""
	items = []
	for i, (name, battery) in enumerate(devices):
		text = name
		if battery and battery[0] is not None:
			text += f' · {battery[0]} %' + (' (charging)' if battery[1].lower().startswith('charging') else '')
		items.append((100 + i, {'label': text, 'enabled': False}))
	if not devices:
		items.append((99, {'label': 'No Logitech device connected', 'enabled': False}))
	items.append((2, {'type': 'separator'}))
	for n, (_key, text, on, _flip) in enumerate(switches):
		items.append((10 + n, {'label': text, 'toggle-type': 'checkmark', 'toggle-state': 1 if on else 0}))
	items.append((3, {'type': 'separator'}))
	items.append((1, {'label': 'Open Lghub'}))
	items.append((QUIT, {'label': 'Quit Lghub'}))
	return items


def _props(props):
	out = {}
	for k, v in props.items():
		if isinstance(v, bool):
			out[k] = GLib.Variant('b', v)
		elif isinstance(v, int):
			out[k] = GLib.Variant('i', v)
		else:
			out[k] = GLib.Variant('s', v)
	return out


class Tray:
	"""Used by the engine: runs the tray on its own thread with its own GLib main loop."""

	def __init__(self, devices=lambda: []):
		self.devices = devices            # -> [(name, battery reading)]
		self.revision = 1
		self.items, self.switches = [], []
		self.conn = None
		self.loop = None
		self.thread = threading.Thread(target=self._run, daemon=True)

	def start(self):
		self.thread.start()

	def stop(self):
		if self.loop:
			self.loop.quit()

	def refresh(self):
		"""Rebuild the menu (called from any thread)."""
		if self.loop:
			self.loop.get_context().invoke_full(GLib.PRIORITY_DEFAULT, self._rebuild)

	def _rebuild(self):
		try:
			self.switches = _switches()
		except (OSError, ValueError):
			self.switches = []
		self.items = menu_items(self.devices(), self.switches)
		self.revision += 1
		if self.conn:
			self.conn.emit_signal(None, MENU_PATH, 'com.canonical.dbusmenu', 'LayoutUpdated',
			                      GLib.Variant('(ui)', (self.revision, 0)))
		return False

	def _run(self):
		context = GLib.MainContext()
		context.push_thread_default()
		self.loop = GLib.MainLoop(context)
		try:
			self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
		except GLib.Error:
			return
		self._rebuild()
		self.conn.register_object(ITEM_PATH, Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0],
		                          self._item_call, self._item_get, None)
		self.conn.register_object(MENU_PATH, Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0],
		                          self._menu_call, self._menu_get, None)
		name = f'org.kde.StatusNotifierItem-{os.getpid()}-1'
		Gio.bus_own_name_on_connection(self.conn, name, Gio.BusNameOwnerFlags.NONE, None, None)
		self.conn.call(WATCHER, '/StatusNotifierWatcher', WATCHER, 'RegisterStatusNotifierItem',
		               GLib.Variant('(s)', (name,)), None, Gio.DBusCallFlags.NONE, -1, None, None)
		tick = GLib.timeout_source_new_seconds(30)            # the battery readings move on
		tick.set_callback(lambda *_: self._rebuild() or True)
		tick.attach(context)
		self.loop.run()

	# --- StatusNotifierItem --------------------------------------------------------------------

	def _item_get(self, _conn, _sender, _path, _iface, prop):
		icon = icon_name()
		values = {'Category': ('s', 'Hardware'), 'Id': ('s', 'lghub'), 'Title': ('s', 'Lghub'),
		          'Status': ('s', 'Active'), 'IconName': ('s', icon), 'IconThemePath': ('s', ICONS),
		          'ToolTip': ('(sa(iiay)ss)', (icon, [], 'Lghub', self._tooltip())),
		          'Menu': ('o', MENU_PATH), 'ItemIsMenu': ('b', True)}
		kind, value = values.get(prop, ('s', ''))
		return GLib.Variant(kind, value)

	def _tooltip(self):
		return '\n'.join(props['label'] for i, props in self.items if i >= 99)

	def _item_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
		if method == 'Activate':
			open_app()
		invocation.return_value(None)

	# --- com.canonical.dbusmenu ----------------------------------------------------------------

	def _menu_get(self, _conn, _sender, _path, _iface, prop):
		return {'Version': GLib.Variant('u', 3), 'TextDirection': GLib.Variant('s', 'ltr'),
		        'Status': GLib.Variant('s', 'normal'), 'IconThemePath': GLib.Variant('as', [])}.get(prop)

	def _layout(self):
		children = [GLib.Variant('(ia{sv}av)', (i, _props(p), [])) for i, p in self.items]
		return GLib.Variant('(u(ia{sv}av))', (self.revision, (0, {'children-display': GLib.Variant('s', 'submenu')},
		                                                       children)))

	def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
		if method == 'GetLayout':
			invocation.return_value(self._layout())
		elif method == 'GetGroupProperties':
			ids = params.unpack()[0]
			rows = [(i, _props(p)) for i, p in self.items if not ids or i in ids]
			invocation.return_value(GLib.Variant('(a(ia{sv}))', (rows,)))
		elif method == 'GetProperty':
			i, name = params.unpack()
			props = dict(self.items).get(i, {})
			invocation.return_value(GLib.Variant('(v)', (_props(props).get(name, GLib.Variant('s', '')),)))
		elif method == 'Event':
			i, event, _data, _time = params.unpack()
			if event == 'clicked':
				self._clicked(i)
			invocation.return_value(None)
		elif method == 'EventGroup':
			for i, event, _data, _time in params.unpack()[0]:
				if event == 'clicked':
					self._clicked(i)
			invocation.return_value(GLib.Variant('(ai)', ([],)))
		elif method == 'AboutToShow':
			invocation.return_value(GLib.Variant('(b)', (False,)))
		else:                                          # AboutToShowGroup
			invocation.return_value(GLib.Variant('(aiai)', ([], [])))

	def _clicked(self, item):
		if item == 1:
			open_app()
		elif item == QUIT:
			threading.Thread(target=quit_all, args=(self.conn,), daemon=True).start()
		elif 10 <= item < 10 + len(self.switches):
			self.switches[item - 10][3]()
			self._rebuild()
