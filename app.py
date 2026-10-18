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
import devices  # noqa: E402
import mouse_ui  # noqa: E402
from ui import APP_DIR, CSS, box, device_sidebar, label, nav_button, page_header, scrolled  # noqa: E402

APP_ID = 'dev.local.LghubBlueVoice'
APP_NAME = 'Lghub'
DISCOVER_SECONDS = 2


# --- home: connected devices ---------------------------------------------------------------

def device_tile(icon_name, name, kind, detail, on_click, icon_file=None):
	b = Gtk.Button()
	b.add_css_class('tile')
	inner = box(spacing=6, valign=Gtk.Align.CENTER)
	icon = Gtk.Image.new_from_file(icon_file) if icon_file else Gtk.Image.new_from_icon_name(icon_name)
	icon.set_pixel_size(64)
	icon.add_css_class('tile-icon')
	icon.set_margin_bottom(14)
	inner.append(icon)
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
		self.append(page_header('Devices', 'Your connected Logitech G gear. Pick one to set it up.'))
		self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=16, row_spacing=16,
		                        min_children_per_line=1, max_children_per_line=5, homogeneous=True,
		                        valign=Gtk.Align.START)
		self.append(self.flow)
		self.append(label('Software', ['section-title']))
		soft = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=16, row_spacing=16,
		                   min_children_per_line=1, max_children_per_line=5, homogeneous=True)
		icon_path = os.path.join(APP_DIR, 'lghub-bluevoice.svg')
		soft.append(device_tile('audio-input-microphone-symbolic', bluevoice_ui.APP_TITLE, 'Virtual microphone',
		                        'Works with any microphone', lambda: win.show_device(None),
		                        icon_path if os.path.exists(icon_path) else None))
		self.append(soft)
		self.empty = label('No Logitech devices found. Plug one in; it shows up here within a few seconds.',
		                   ['muted'], wrap=True)
		self.append(self.empty)
		self.devices = []

	def show(self, found):
		self.devices = found
		while (child := self.flow.get_first_child()):
			self.flow.remove(child)
		for dev in found:
			detail = 'Connected' if dev.model.type != 'receiver' else 'Paired devices: coming soon'
			self.flow.append(device_tile(dev.icon, dev.name, dev.type_name, detail,
			                             lambda d=dev: self.win.show_device(d)))
		self.flow.set_visible(bool(found))
		self.empty.set_visible(not found)


# --- other devices -------------------------------------------------------------------------

ZONE_NAMES = {'primary': 'Main', 'branding': 'Logo', 'combined': 'All'}


class DeviceView(Gtk.Box):
	"""A device without its own settings pages yet: what it is, and what G HUB offers for it."""

	def __init__(self, win, device):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
		self.device = device
		icon = Gtk.Image.new_from_icon_name(device.icon)
		icon.add_css_class('device-icon')
		side = device_sidebar(win.show_home, icon, device.name, device.type_name)
		nav = box(spacing=4)
		overview = nav_button('Overview', 'view-grid-symbolic', lambda: None)
		overview.add_css_class('active')
		nav.append(overview)
		side.append(nav)
		self.append(side)

		page = box(spacing=20, css=['page'])
		page.append(page_header(device.name, f'{device.type_name} · connected over USB'))

		hero = box(Gtk.Orientation.HORIZONTAL, 20, ['card', 'hero'])
		big = Gtk.Image.new_from_icon_name(device.icon)
		big.set_pixel_size(72)
		big.add_css_class('device-icon')
		hero.append(big)
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
		card.append(label(f'Lghub recognises this {device.type_name.lower()}, but its settings page isn’t '
		                  'built yet. It’s on the way.', ['muted'], wrap=True))
		page.append(card)
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

		self._discover()
		GLib.timeout_add_seconds(DISCOVER_SECONDS, self._discover)
		if start_page in bluevoice_ui.PAGES:
			pro_x = next((d for d in self.home.devices if devices.blue_voice_model(d)), None)
			self.show_device(pro_x)
			self.blue_voice.show_page(start_page)
		elif start_page.startswith('device:'):
			wanted = start_page.split(':', 1)[1]
			match = next((d for d in self.home.devices if d.model.key == wanted or d.usb_id.endswith(wanted)), None)
			if match:
				self.show_device(match)

	def toast(self, text):
		self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

	def show_home(self):
		self.current = None
		self.stack.set_visible_child_name('home')

	def show_device(self, device):
		"""Open a device's page; None opens Blue VO!CE without a headset."""
		self.current = device
		if device is None or devices.blue_voice_model(device):
			self.blue_voice.set_device(device)
			self.stack.set_visible_child_name('bluevoice')
			return
		if self.device_view:
			if hasattr(self.device_view, 'close'):
				self.device_view.close()
			self.stack.remove(self.device_view)
		view = {'mouse': mouse_ui.MouseView}.get(device.model.type, DeviceView)
		self.device_view = view(self, device)
		self.stack.add_named(self.device_view, 'device')
		self.stack.set_visible_child_name('device')

	def _discover(self):
		found = devices.discover()
		if [d.id for d in found] != [d.id for d in self.home.devices] or not self.home.devices:
			self.home.show(found)
		if self.current and self.current.id not in {d.id for d in found}:
			self.toast(f'{self.current.name} was disconnected')
			if devices.blue_voice_model(self.current):
				self.blue_voice.set_device(None)  # Blue VO!CE keeps working with another mic
				self.current = None
			else:
				self.show_home()
		return True


class App(Adw.Application):
	def __init__(self):
		super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

	def do_startup(self):
		Adw.Application.do_startup(self)
		Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
		provider = Gtk.CssProvider()
		provider.load_from_string(CSS)
		Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
		                                          Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

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
