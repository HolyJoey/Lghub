#!/usr/bin/env python3
"""Lghub: Logitech G devices on Linux (GTK4 + libadwaita).

The home screen lists connected devices; each opens its own page.
"""
import os
import sys

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

import bluevoice_ui  # noqa: E402
import games_ui  # noqa: E402
import pairing  # noqa: E402
import pairing_ui  # noqa: E402
import settings_ui  # noqa: E402
import update_ui  # noqa: E402
import devices  # noqa: E402
import hidpp_ui  # noqa: E402
import depots  # noqa: E402
import mouse_ui  # noqa: E402
import webcam_ui  # noqa: E402
from worker import Worker  # noqa: E402
from ui import (CSS, box, button_widget, device_icon, device_sidebar, forget_image, label, nav_button,  # noqa: E402
                page_header, scrolled)

APP_ID = 'dev.local.Lghub'
APP_NAME = 'Lghub'
DISCOVER_SECONDS = 2
RECEIVER_SCAN_SECONDS = 10
TILE_PICTURE = 110


# --- home: connected devices ---------------------------------------------------------------

def device_tile(icon, name, kind, detail, on_click):
	"""icon: a widget (photo or symbolic icon)."""
	b = Gtk.Button()
	b.add_css_class('tile')
	inner = box(spacing=6, valign=Gtk.Align.CENTER)
	if not icon.has_css_class('photo'):
		icon.add_css_class('tile-icon')
		icon.set_pixel_size(64)
	frame = box(height_request=TILE_PICTURE, margin_bottom=12)
	icon.set_halign(Gtk.Align.CENTER)
	icon.set_valign(Gtk.Align.CENTER)
	icon.set_vexpand(True)
	frame.append(icon)
	inner.append(frame)
	inner.append(label(name, ['tile-name'], xalign=0.5, ellipsize=Pango.EllipsizeMode.END))
	inner.append(label(kind, ['muted', 'small'], xalign=0.5))
	inner.append(label(detail, ['ok', 'small'], xalign=0.5))
	b.set_child(inner)
	b.connect('clicked', lambda _w: on_click())
	return b


class HomePage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24, css_classes=['page'])
		self.win = win
		self.banner = update_ui.UpdateBanner(win)
		self.append(self.banner.widget)
		self.append(page_header('Devices', 'Your connected Logitech G gear. Pick one to set it up.',
		                        button_widget('Games', ['ghost'], win.show_games),
		                        button_widget('Settings', ['ghost'], win.show_settings)))
		self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=16, row_spacing=16,
		                        min_children_per_line=1, max_children_per_line=5, homogeneous=True,
		                        valign=Gtk.Align.START)
		self.append(self.flow)
		self.empty = label('No Logitech devices found. Plug one in; it shows up here within a few seconds.',
		                   ['muted'], wrap=True)
		self.append(self.empty)
		self.devices = []

	def show(self, found):
		self.banner.refresh()
		self.devices = found
		while (child := self.flow.get_first_child()):
			self.flow.remove(child)
		for dev in found:
			if dev.model.type == 'receiver':
				detail = 'No wireless device switched on'
			else:
				detail = 'Connected' if dev.link == 'USB' else dev.link.capitalize()
			self.flow.append(device_tile(device_icon(dev, TILE_PICTURE), dev.name, dev.type_name, detail,
			                             lambda d=dev: self.win.show_device(d)))
		self.flow.set_visible(bool(found))
		self.empty.set_visible(not found)


# --- other devices -------------------------------------------------------------------------

ZONE_NAMES = {'primary': 'Main', 'branding': 'Logo', 'combined': 'All'}


class DeviceView(Gtk.Box):
	"""A receiver with nothing switched on, or a device we can't talk to: what it is, and
	what G HUB offers for the model."""

	def __init__(self, win, device):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
		self.device = device
		icon = device_icon(device, 32)
		side = device_sidebar(win.show_home, icon, device.name, device.type_name)
		nav = box(spacing=4)
		overview = nav_button('Overview', 'view-grid-symbolic', lambda: None)
		overview.add_css_class('active')
		nav.append(overview)
		side.append(nav)
		self.append(side)

		page = box(spacing=20, css=['page'])
		page.append(page_header(device.name, f'{device.type_name} · connected over {device.link}'))

		hero = box(Gtk.Orientation.HORIZONTAL, 20, ['card', 'hero'])
		hero.append(device_icon(device, 72))
		facts = box(spacing=6, hexpand=True, valign=Gtk.Align.CENTER)
		facts.append(label(device.name, ['big-word']))
		facts.append(label(f'USB {device.usb_id}' + (f' · serial {device.serial}' if device.serial else ''),
		                   ['muted', 'small', 'mono'], selectable=True))
		hero.append(facts)
		page.append(hero)

		features = self._features(device.model)
		if features:
			card = box(spacing=12, css=['card'])
			card.append(label('What this model can do', ['section-title']))
			for title, chips in features:
				row = box(Gtk.Orientation.HORIZONTAL, 14)
				row.append(label(title, ['muted'], width_chars=18))
				flow = box(Gtk.Orientation.HORIZONTAL, 6)
				for chip in chips:
					flow.append(label(chip, ['chip']))
				row.append(flow)
				card.append(row)
			page.append(card)

		card = box(spacing=8, css=['card'])
		card.append(label('Settings', ['section-title']))
		if device.model.type == 'receiver':
			text = ('No wireless device on this receiver is switched on. Switch one on; it shows up on the home '
			        'screen within a few seconds.')
		else:
			text = f'Lghub recognises this {device.type_name.lower()}, but can’t change its settings yet.'
		card.append(label(text, ['muted'], wrap=True))
		page.append(card)
		if device.model.type == 'receiver' and pairing.can_pair(device):
			page.append(pairing_ui.pair_card(device))
		self.append(scrolled(page))

	@staticmethod
	def _features(model):
		features = []
		if model.lighting:
			zones = [ZONE_NAMES.get(z, z.replace('_', ' ').capitalize()) for z in model.lighting]
			features.append(('Lighting zones', zones))
		if 'onboard' in model.flags:
			features.append(('Memory', ['Onboard profiles']))
		if 'battery' in model.flags:
			features.append(('Power', ['Battery']))
		if model.type == 'mouse':
			features.append(('Sensor', ['DPI levels', 'Report rate']))
		if model.type == 'camera':
			features.append(('Picture', ['Brightness', 'Contrast', 'Focus', 'Zoom', 'White balance']))
		return features


# --- window --------------------------------------------------------------------------------

class MainWindow(Adw.ApplicationWindow):
	def __init__(self, app, start_page='home'):
		super().__init__(application=app, title=APP_NAME, default_width=1100, default_height=760)
		self.toasts = Adw.ToastOverlay()
		self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
		self.stack.add_css_class('app-bg')
		self.toasts.set_child(self.stack)
		self.set_content(self.toasts)

		self.home = HomePage(self)
		self.stack.add_named(scrolled(self.home), 'home')
		self.blue_voice = bluevoice_ui.BlueVoiceView(self)
		self.stack.add_named(self.blue_voice, 'bluevoice')
		self.device_view = None
		self.current = None  # the Device whose page is open (None: home, or Blue VO!CE on its own)
		self.found = []
		self.paired = {}       # receiver id -> devices paired to it and switched on
		self.scanned = {}      # receiver id -> when it was last asked
		self.scanner = Worker()
		self.pictures = Worker()  # downloads product pictures, one at a time
		self.asked = set()        # models whose picture was looked for this run
		self.pending = start_page if start_page.startswith('device:') else None

		self._discover()
		GLib.timeout_add_seconds(DISCOVER_SECONDS, self._discover)
		if start_page == 'games':
			self.show_games()
		if start_page == 'settings':
			self.show_settings()
		if start_page in bluevoice_ui.PAGES:
			pro_x = next((d for d in self.home.devices if devices.blue_voice_model(d)), None)
			self.show_device(pro_x)
			self.blue_voice.show_page(start_page)
		self._open_pending()

	def _open_pending(self):
		"""--page device:<model or pid>: open it once it has been found."""
		if not self.pending:
			return
		wanted = self.pending.split(':', 1)[1]
		match = next((d for d in self.home.devices if d.model.key == wanted or d.usb_id.endswith(wanted)
		              or d.id.endswith(wanted)), None)
		if match:
			self.pending = None
			self.show_device(match)

	def toast(self, text):
		self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

	def show_home(self):
		self.current = None
		self.stack.set_visible_child_name('home')

	def show_games(self):
		self.current = None
		if not self.stack.get_child_by_name('games'):
			self.stack.add_named(scrolled(games_ui.GamesPage(self)), 'games')
		self.stack.set_visible_child_name('games')

	def show_settings(self):
		self.current = None
		if self.stack.get_child_by_name('settings'):
			self.stack.remove(self.stack.get_child_by_name('settings'))      # fresh: the games list may have changed
		self.stack.add_named(scrolled(settings_ui.SettingsPage(self)), 'settings')
		self.stack.set_visible_child_name('settings')

	def show_device(self, device):
		"""Open a device's page (None: the headset view without a headset, for --page)."""
		self.current = device
		if device is None or devices.blue_voice_model(device):
			self.blue_voice.set_device(device)
			self.stack.set_visible_child_name('bluevoice')
			return
		if self.device_view:
			if hasattr(self.device_view, 'close'):
				self.device_view.close()
			self.stack.remove(self.device_view)
		views = {'mouse': mouse_ui.MouseView, 'camera': webcam_ui.WebcamView, 'receiver': DeviceView}
		view = views.get(device.model.type, hidpp_ui.GenericView)
		self.device_view = view(self, device)
		self.stack.add_named(self.device_view, 'device')
		self.stack.set_visible_child_name('device')

	def _discover(self):
		self.found = devices.discover()
		receivers = [d for d in self.found if d.model.type == 'receiver']
		ids = {r.id for r in receivers}
		for gone in set(self.paired) - ids:
			self.paired.pop(gone)
			self.scanned.pop(gone, None)
		now = GLib.get_monotonic_time() / 1e6
		for r in receivers:
			busy = self.current is not None and self.current.id.startswith(r.id + '#')
			if not busy and now - self.scanned.get(r.id, -1e9) >= RECEIVER_SCAN_SECONDS:
				self.scanned[r.id] = now
				self.scanner.submit(lambda r=r: devices.scan_receiver(r),
				                    lambda paired, r=r: self._paired(r.id, paired), lambda _e: None)
		self._show_devices()
		return True

	def _fetch_pictures(self, shown):
		for d in shown:
			key = d.model.key
			if key in self.asked:
				continue
			self.asked.add(key)
			if key in depots.PRESET_FILES:
				self.pictures.submit(lambda k=key: depots.fetch_presets(k),
				                     lambda path: path and self.blue_voice.refresh_model())
			if key in depots.DEPOTS and not os.path.exists(depots.path_for(key)):
				self.pictures.submit(lambda k=key: depots.fetch_picture(k),
				                     lambda path, k=key: path and self._got_picture(k))
			if d.model.type in ('keyboard', 'mouse') and key in depots.DEPOTS:
				# the per-key page's layout, the device's own LED map and effects, before its page opens
				self.pictures.submit(lambda k=key: (depots.fetch_metadata(k), depots.fetch_light_map(k),
				                                    depots.fetch_device_effects(k)))

	def _got_picture(self, key):
		forget_image(key)
		self.home.show(self.home.devices)

	def _paired(self, receiver_id, paired):
		if receiver_id in self.scanned:
			self.paired[receiver_id] = paired
			self._show_devices()

	def _show_devices(self):
		shown = []
		for d in self.found:
			paired = self.paired.get(d.id)
			shown.extend(paired if paired else [d])
		if [d.id for d in shown] != [d.id for d in self.home.devices] or not self.home.devices:
			self.home.show(shown)
		self._fetch_pictures(shown)
		self._open_pending()
		if self.current and self.current.id not in {d.id for d in shown}:
			self.toast(f'{self.current.name} was disconnected')
			self.show_home()


class App(Adw.Application):
	def __init__(self):
		super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

	def do_startup(self):
		Adw.Application.do_startup(self)
		Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
		theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
		Gtk.Window.set_default_icon_name('lghub' if theme.has_icon('lghub') else 'lghub-logo')
		provider = Gtk.CssProvider()
		provider.load_from_string(CSS)
		Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
		                                          Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
		quit_action = Gio.SimpleAction.new('quit', None)       # the tray's Quit closes the window too
		quit_action.connect('activate', lambda *_: self.quit())
		self.add_action(quit_action)

	def do_activate(self):
		page = 'home'
		argv = sys.argv
		if '--page' in argv and argv.index('--page') + 1 < len(argv):
			page = argv[argv.index('--page') + 1]
		win = self.props.active_window or MainWindow(self, page)
		win.present()
		if '--screenshot' in argv and argv.index('--screenshot') + 1 < len(argv):
			path = argv[argv.index('--screenshot') + 1]
			GLib.timeout_add(2500, self._screenshot, win, path)

	def _screenshot(self, win, path):
		"""Render the window itself to a PNG (for the README); independent of the screen."""
		paintable = Gtk.WidgetPaintable.new(win)
		snapshot = Gtk.Snapshot()
		paintable.snapshot(snapshot, win.get_width(), win.get_height())
		node = snapshot.to_node()
		if node:
			win.get_renderer().render_texture(node, None).save_to_png(path)
		self.quit()
		return False


if __name__ == '__main__':
	App().run(None)
