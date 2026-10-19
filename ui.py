"""Shared look and building blocks for every page."""
import os

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

import store  # noqa: E402

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ACCENT = '#2f8cff'
NOTIFY_ACTIVE = 'notify::active'

CSS = f"""
window {{ font-family: Manrope, Cantarell, sans-serif; }}
.app-bg {{ background: #111317; color: #eceef2; }}
.sidebar {{ background: #0c0e11; border-right: 1px solid #22262e; padding: 24px 16px; }}
.brand-title {{ font-weight: 700; font-size: 15px; }}
.muted {{ color: #9aa0ad; }}
.small {{ font-size: 12px; }}
button.nav {{ min-height: 44px; padding: 0 12px; border-radius: 10px; background: transparent;
  color: #9aa0ad; font-weight: 500; box-shadow: none; border: none; }}
button.nav:hover {{ background: #161a20; }}
button.nav.active {{ background: #1c2027; color: #eceef2; font-weight: 600; }}
button.nav.active image {{ color: {ACCENT}; }}
.card {{ background: #161a20; border: 1px solid #22262e; border-radius: 14px; padding: 16px 20px; }}
.card.off {{ opacity: 0.55; }}
.hero {{ background: linear-gradient(135deg, #14243a, #161a20 60%); border-color: #1f3a5c; }}
.big-word {{ font-size: 26px; font-weight: 700; }}
.mono {{ font-family: "JetBrains Mono", "JetBrainsMono Nerd Font", monospace; }}
.ok {{ color: #6fdc9a; }}
.warn {{ color: #ffc14d; }}
.err {{ color: #ff8a8a; }}
.page {{ padding: 32px 40px; }}
.page-title {{ font-size: 26px; font-weight: 700; }}
.section-title {{ font-size: 15px; font-weight: 600; }}
.stage-title {{ font-size: 16px; font-weight: 700; }}
button.apply {{ background: {ACCENT}; color: #04121f; font-weight: 700; border-radius: 10px;
  min-height: 40px; padding: 0 20px; border: none; box-shadow: none; }}
button.ghost {{ background: transparent; border: 1px solid #2c313b; color: #eceef2; font-weight: 600;
  border-radius: 10px; min-height: 40px; padding: 0 16px; box-shadow: none; }}
button.danger {{ background: transparent; border: 1px solid #5a2a2a; color: #ff8a8a; font-weight: 600;
  border-radius: 10px; min-height: 40px; padding: 0 16px; box-shadow: none; }}
button.preset {{ background: #161a20; border: 1px solid #22262e; border-radius: 12px; min-height: 64px;
  min-width: 168px; padding: 8px 14px; box-shadow: none; color: #eceef2; }}
button.preset:hover {{ background: #1b1f26; }}
button.preset.selected {{ border: 2px solid {ACCENT}; background: #15223a; padding: 7px 13px; }}
.preset-name {{ font-weight: 700; }}
levelbar.meter trough {{ min-height: 8px; background: #262a33; border-radius: 4px; border: none; }}
levelbar.meter block.filled {{ background: {ACCENT}; border-radius: 4px; }}
levelbar.meter block.high {{ background: #ffc14d; border-radius: 4px; }}
levelbar.meter block.full {{ background: #ff8a8a; border-radius: 4px; }}
levelbar.meter block.empty {{ background: transparent; }}
scale highlight {{ background: {ACCENT}; }}
scale slider {{ background: #eceef2; }}
switch:checked {{ background: {ACCENT}; }}
list.plain {{ background: none; }}
list.plain > row {{ background: #161a20; border: 1px solid #22262e; border-radius: 12px; margin-bottom: 8px; padding: 8px 12px; }}
.value {{ font-family: "JetBrains Mono", "JetBrainsMono Nerd Font", monospace; color: #c9ced8; }}
banner {{ background: #3a2a14; }}
button.back {{ min-height: 36px; padding: 0 10px; border-radius: 10px; background: transparent; color: #9aa0ad;
  box-shadow: none; border: none; font-weight: 500; }}
button.back:hover {{ background: #161a20; color: #eceef2; }}
button.tile {{ background: #161a20; border: 1px solid #22262e; border-radius: 16px; padding: 22px 20px;
  min-width: 200px; min-height: 190px; box-shadow: none; color: #eceef2; }}
button.tile:hover {{ background: #1b1f26; border-color: #2f3644; }}
button.tile image.tile-icon {{ color: {ACCENT}; }}
.tile-name {{ font-size: 16px; font-weight: 700; }}
.device-icon {{ color: {ACCENT}; }}
.photo {{ background: radial-gradient(circle, rgba(120, 150, 200, 0.28) 0%, rgba(120, 150, 200, 0) 68%); }}
.chip {{ background: #1c2027; border-radius: 8px; padding: 4px 10px; font-size: 12px; color: #c9ced8; }}
"""

# --- helpers -------------------------------------------------------------------------------

def box(orientation=Gtk.Orientation.VERTICAL, spacing=0, css=None, **kw):
	b = Gtk.Box(orientation=orientation, spacing=spacing, **kw)
	for c in (css or []):
		b.add_css_class(c)
	return b


def label(text, css=None, xalign=0.0, **kw):
	lbl = Gtk.Label(label=text, xalign=xalign, **kw)
	for c in (css or []):
		lbl.add_css_class(c)
	return lbl


def button_widget(text, css=None, on_click=None):
	b = Gtk.Button(label=text)
	for c in (css or []):
		b.add_css_class(c)
	if on_click:
		b.connect('clicked', lambda _w: on_click())
	return b


def page_header(title, subtitle, *buttons):
	header = box(Gtk.Orientation.HORIZONTAL, 12)
	titles = box(spacing=4, hexpand=True)
	titles.append(label(title, ['page-title']))
	titles.append(label(subtitle, ['muted'], wrap=True))
	header.append(titles)
	for b in buttons:
		b.set_valign(Gtk.Align.CENTER)
		header.append(b)
	return header


def format_value(value, unit):
	if unit == 'Hz':
		return f'{value / 1000:.2f} kHz' if value >= 1000 else f'{value:.0f} Hz'
	if unit == 'dB':
		return f'{value:+.1f} dB' if abs(value) >= 0.05 else '0.0 dB'
	if unit == 'ms':
		return f'{value:.1f} ms' if value < 10 else f'{value:.0f} ms'
	if unit == ':1':
		return f'{value:.1f}:1'
	return f'{value:.1f}'


def meter_bar():
	bar = Gtk.LevelBar(min_value=0, max_value=60, hexpand=True, valign=Gtk.Align.CENTER)
	bar.add_css_class('meter')
	for name in ('low', 'high', 'full'):
		bar.remove_offset_value(name)
	bar.add_offset_value('filled', 48)
	bar.add_offset_value('high', 57)
	bar.add_offset_value('full', 60)
	return bar


def set_meter(bar, value_label, db):
	db = max(-60.0, min(0.0, db))
	bar.set_value(db + 60)
	value_label.set_text('—' if db <= -59.9 else f'{db:.0f} dB')

# --- shared device layout ------------------------------------------------------------------

def device_sidebar(on_back, icon, title, subtitle):
	"""The left column of every device page: back to the device list, then the device."""
	side = box(spacing=28, css=['sidebar'], width_request=232)
	side.set_hexpand(False)
	back = Gtk.Button()
	back.add_css_class('back')
	content = box(Gtk.Orientation.HORIZONTAL, 8)
	content.append(Gtk.Image.new_from_icon_name('go-previous-symbolic'))
	content.append(label('All devices'))
	back.set_child(content)
	back.set_halign(Gtk.Align.START)
	back.connect('clicked', lambda _w: on_back())
	brand = box(spacing=10)
	brand.append(back)
	head = box(Gtk.Orientation.HORIZONTAL, 10)
	icon.set_pixel_size(32)
	head.append(icon)
	titles = box(spacing=2, valign=Gtk.Align.CENTER)
	titles.append(label(title, ['brand-title']))
	titles.append(label(subtitle, ['muted', 'small']))
	head.append(titles)
	brand.append(head)
	side.append(brand)
	return side


def nav_button(text, icon_name, on_click):
	b = Gtk.Button()
	b.add_css_class('nav')
	content = box(Gtk.Orientation.HORIZONTAL, 12)
	content.append(Gtk.Image.new_from_icon_name(icon_name))
	content.append(label(text))
	b.set_child(content)
	b.connect('clicked', lambda _w: on_click())
	return b


def scrolled(child):
	return Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=child, hexpand=True)



_textures = {}


def product_image(model_key, size):
	"""The model's product photo scaled to fit size x size, or None when we don't have one."""
	path = os.path.join(store.IMAGE_DIR, f'{model_key}.png')
	if (path, size) not in _textures:
		try:
			pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, size, size, True)
			_textures[(path, size)] = Gdk.Texture.new_for_pixbuf(pixbuf)
		except GLib.Error:
			_textures[(path, size)] = None
	texture = _textures[(path, size)]
	if texture is None:
		return None
	picture = Gtk.Image.new_from_paintable(texture)
	picture.set_pixel_size(size)
	picture.add_css_class('photo')
	return picture


_waiting = {}   # model key -> [(icon holder, size)] still showing the type's icon (until the photo comes)


class _IconHolder(Gtk.Box):
	"""The type's icon until the product photo arrives (forget_image puts it in)."""

	def set_pixel_size(self, size):
		child = self.get_first_child()
		if isinstance(child, Gtk.Image) and not child.has_css_class('photo'):
			child.set_pixel_size(size)


def forget_image(model_key):
	"""Drop cached lookups for a model, e.g. after its picture was downloaded, and put the
	picture into icons already on screen."""
	path = os.path.join(store.IMAGE_DIR, f'{model_key}.png')
	for key in [k for k in _textures if k[0] == path]:
		_textures.pop(key)
	for holder, size in _waiting.pop(model_key, []):
		picture = product_image(model_key, size) if holder.get_first_child() else None
		if picture:
			holder.remove(holder.get_first_child())
			holder.append(picture)


def device_icon(device, size):
	"""Photo if we have one, else the device type's symbolic icon (replaced by the photo when
	it arrives)."""
	picture = product_image(device.model.key, size)
	if picture:
		return picture
	icon = Gtk.Image.new_from_icon_name(device.icon)
	icon.set_pixel_size(size)
	icon.add_css_class('device-icon')
	holder = _IconHolder(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
	holder.append(icon)
	_waiting.setdefault(device.model.key, []).append((holder, size))
	return holder
