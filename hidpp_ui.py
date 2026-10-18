"""The page for keyboards, headsets, speakers and anything else: the HID++ settings panel,
plus the controls of the device's USB sound card if it has one."""
from gi.repository import Gtk

import headset
import headset_ui
import macros_ui
import perkey_ui
from hidpp_panel import SettingsPanel
from ui import box, device_icon, device_sidebar, label, nav_button, page_header, scrolled


class GenericView(Gtk.Box):
	def __init__(self, win, device):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
		self.win = win
		self.device = device

		side = device_sidebar(win.show_home, device_icon(device, 32), device.name, device.type_name)
		self.nav = box(spacing=4)
		self.nav_buttons = {}
		side.append(self.nav)
		side.append(box(vexpand=True))
		side_card = box(spacing=6, css=['card'])
		self.side_title = label('Connecting…', ['muted', 'small'], wrap=True, max_width_chars=24)
		side_card.append(self.side_title)
		self.side_detail = label('', ['small'], wrap=True, max_width_chars=24)
		side_card.append(self.side_detail)
		side.append(side_card)
		self.append(side)

		self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True)
		page = box(spacing=20, css=['page'])
		page.append(page_header(device.name, f'{device.type_name}'
		                        + (' · wireless' if device.wireless else ' · connected over USB')))
		self.panel = SettingsPanel(win, device, self._status)
		page.append(self.panel)
		self.stack.add_named(scrolled(page), 'settings')
		self._add_nav('settings', 'Settings', 'emblem-system-symbolic')
		if device.model.type == 'keyboard':
			if perkey_ui.load_layout(device.model.key):
				self.perkey = perkey_ui.PerKeyPage(win, device, self._apply_perkey)
				self.stack.add_named(scrolled(self.perkey), 'perkey')
				self._add_nav('perkey', 'Per-key lighting', 'input-keyboard-symbolic')
			gkeys = perkey_ui.gkey_count(device.model.key) or 0
			self.stack.add_named(scrolled(macros_ui.MacrosPage(win, device, [(f'gkey:{i}', f'G{i}')
			                                                                  for i in range(1, gkeys + 1)])),
			                     'macros')
			self._add_nav('macros', 'Macros', 'media-record-symbolic')
		self.audio = None
		if not device.wireless and headset.alsa_card(device.port) is not None:
			self.audio = headset_ui.HeadsetPage(win, hidpp=False)
			self.stack.add_named(scrolled(self.audio), 'audio')
			self._add_nav('audio', 'Sound', 'audio-volume-high-symbolic')
			self.audio.set_device(device)
		self.append(self.stack)
		self.show_page('settings')

	def close(self):
		self.panel.close()
		if self.audio:
			self.audio.close()

	def _apply_perkey(self, colors):
		"""Send per-key colours to the keyboard (HID++ 0x8081; see perkey.py)."""
		self.panel.apply_perkey(colors)

	def _status(self, title, detail):
		self.side_title.set_text(title)
		self.side_detail.set_text(detail)

	def _add_nav(self, key, text, icon):
		b = nav_button(text, icon, lambda: self.show_page(key))
		self.nav.append(b)
		self.nav_buttons[key] = b

	def show_page(self, key):
		self.stack.set_visible_child_name(key)
		for k, b in self.nav_buttons.items():
			(b.add_css_class if k == key else b.remove_css_class)('active')
		if key == 'audio' and self.audio:
			self.audio.refresh()
