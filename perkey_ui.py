"""Per-key lighting: the keyboard's picture with every key where G HUB draws it (its metadata.json),
click keys to select them, pick a colour. The colours are kept per keyboard; apply(colors) sends
them to the device (set by the page's owner, which knows the protocol)."""
import json
import math
import os
import threading

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

import depots
import perkey
import store
from ui import box, button_widget, label, page_header

SHORTCUTS = (('WASD', ('PERKEY_KEYBOARD', (0x1a, 0x04, 0x16, 0x07))),
             ('Arrows', ('PERKEY_KEYBOARD', (0x4f, 0x50, 0x51, 0x52))),
             ('F-keys', ('PERKEY_KEYBOARD', tuple(range(0x3a, 0x46)))),
             ('Numbers', ('PERKEY_KEYBOARD', tuple(range(0x1e, 0x28)))))


def load_layout(model):
	return perkey.load_layout(model)


def gkey_count(model):
	"""How many G-keys G HUB draws for this keyboard, or None without its layout."""
	layout = load_layout(model)
	if not layout:
		return None
	return sum(1 for group, *_rest in layout[2] if group == 'PERKEY_GKEY')


def load_colors(model):
	return perkey.load_colors(model)


def save_colors(model, colors):
	perkey.save_colors(model, colors)


class PerKeyPage(Gtk.Box):
	def __init__(self, win, device, apply=None):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16, css_classes=['page'])
		self.win = win
		self.model = device.model.key
		self.apply = apply or (lambda colors: None)
		self.layout = load_layout(self.model)
		self.colors = load_colors(self.model)       # "group:id" -> [r, g, b]
		self.selected = set()
		self.picture = None
		self.append(page_header('Per-key lighting', 'Click keys (or drag across them) to pick them, then '
		                        'choose a colour.'))
		if not self.layout:
			self.append(label('The key layout for this keyboard isn’t downloaded yet. Plug it in once while '
			                  'online.', ['muted'], wrap=True))
			return
		try:   # G HUB's pictures are large; a 1600 px copy is plenty to draw on
			self.picture = GdkPixbuf.Pixbuf.new_from_file_at_scale(f'{store.IMAGE_DIR}/{self.model}.png', 1600, -1, True)
		except GLib.Error:
			self.picture = None
		self.area = Gtk.DrawingArea(hexpand=True, content_height=360)
		self.area.set_draw_func(self._draw)
		click = Gtk.GestureClick()
		click.connect('pressed', self._clicked)
		self.area.add_controller(click)
		drag = Gtk.GestureDrag()
		drag.connect('drag-update', self._dragged)
		drag.connect('drag-begin', self._drag_begin)
		self.area.add_controller(drag)
		self.append(self.area)

		tools = box(Gtk.Orientation.HORIZONTAL, 8)
		tools.append(button_widget('All keys', ['ghost'], self._select_all))
		for name, (group, ids) in SHORTCUTS:
			tools.append(button_widget(name, ['ghost'], lambda g=group, i=ids: self._select(g, i)))
		tools.append(button_widget('None', ['ghost'], self._select_none))
		tools.append(box(hexpand=True))
		self.color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
		rgba = Gdk.RGBA()
		rgba.parse('#2f8cff')
		self.color.set_rgba(rgba)
		tools.append(self.color)
		tools.append(button_widget('Colour selected', ['apply'], self._paint))
		self.append(tools)
		self.status = label('', ['muted', 'small'])
		self.append(self.status)
		self._status()
		self.append(self._lightsync_card())

	# --- LIGHTSYNC ----------------------------------------------------------------------

	def _lightsync_card(self):
		"""G HUB's software effects: the background service lights the keys (lightsync.py)."""
		import lightsync
		import softlight
		settings = lightsync.load().get(self.model, {})
		card = box(spacing=10, css=['card'])
		card.append(label('LIGHTSYNC', ['section-title']))
		card.append(label('Effects the background service plays on the keys: G HUB’s own animations, starlight, '
		                  'colour cycle, the audio visualizer (bass left, treble right) and the screen sampler '
		                  '(needs grim: Hyprland, Sway). Your colours come back when it is off.',
		                  ['muted', 'small'], wrap=True))
		effects = [(None, None, 'Off'), ('audio', None, 'Audio visualizer'), ('screen', None, 'Screen sampler'),
		           ('starlight', None, 'Starlight'), ('cycle', None, 'Colour cycle'), ('echo', None, 'Echo press')]
		cached = os.path.join(softlight.CACHE, os.path.basename(softlight.PREFABS))
		try:
			with open(cached) as f:
				effects += [('keyframe', file, name) for name, file in softlight.keyboard_effects(json.load(f))]
		except (OSError, ValueError):
			threading.Thread(target=softlight.load_prefabs, daemon=True).start()   # there next time
		chosen = next((i for i, (k, f, _n) in enumerate(effects)
		               if k == settings.get('effect') and f == settings.get('file')), 0)
		effect = Gtk.DropDown.new_from_strings([name for _k, _f, name in effects])
		effect.set_selected(chosen)
		card.append(self._lightsync_row('Effect', effect))

		def color_button(rgb):
			b = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
			rgba = Gdk.RGBA()
			rgba.red, rgba.green, rgba.blue = (c / 255 for c in rgb)
			rgba.alpha = 1.0
			b.set_rgba(rgba)
			return b

		def rgb(button):
			c = button.get_rgba()
			return [round(v * 255) for v in (c.red, c.green, c.blue)]

		def slider(lo, hi, value, unit):
			sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
			sc.set_value(value)
			sc.set_draw_value(True)
			sc.set_size_request(280, -1)
			sc.set_format_value_func(lambda _s, v: f'{v:.0f}{unit}')
			return sc

		color = color_button(settings.get('color', [0, 140, 255]))
		boost = slider(0, 100, settings.get('color_boost', 0), ' %')          # G HUB's 0-100 %
		smoothing = Gtk.Switch(active=settings.get('smoothing', False), valign=Gtk.Align.CENTER)
		star = color_button(settings.get('star', [255, 255, 255]))
		sky = color_button(settings.get('sky', [0, 0, 40]))
		count = slider(*softlight.STAR_COUNT, settings.get('count', 50), '')
		speed = slider(*softlight.STAR_SPEED, settings.get('speed', 2000), ' ms')
		cycle_speed = slider(*softlight.CYCLE_SPEED, settings.get('speed', 5000), ' ms')
		echo = color_button(settings.get('echo', [255, 255, 255]))
		rest = color_button(settings.get('rest', [0, 0, 0]))
		echo_speed = slider(*softlight.STAR_SPEED, settings.get('speed', 1000), ' ms')
		rows = {'audio': [('Colour', color)], 'screen': [('Colour boost', boost), ('Smoothing', smoothing)],
		        'starlight': [('Star colour', star), ('Sky colour', sky), ('Stars', count), ('Speed', speed)],
		        'cycle': [('Speed', cycle_speed)],
		        'echo': [('Echo colour', echo), ('Rest colour', rest), ('Fade', echo_speed)]}
		widgets = {}
		for kind, items in rows.items():
			for text, w in items:
				r = self._lightsync_row(text, w)
				card.append(r)
				widgets.setdefault(kind, []).append(r)

		def show():
			kind = effects[effect.get_selected()][0]
			for k, rs in widgets.items():
				for r in rs:
					r.set_visible(k == kind)
			return kind

		def changed(*_):
			kind = show()
			data = lightsync.load()
			values = {'audio': lambda: {'color': rgb(color)},
			          'screen': lambda: {'color_boost': round(boost.get_value()), 'smoothing': smoothing.get_active()},
			          'starlight': lambda: {'star': rgb(star), 'sky': rgb(sky), 'count': round(count.get_value()),
			                                'speed': round(speed.get_value())},
			          'cycle': lambda: {'speed': round(cycle_speed.get_value())},
			          'echo': lambda: {'echo': rgb(echo), 'rest': rgb(rest), 'speed': round(echo_speed.get_value())},
			          'keyframe': lambda: {'file': effects[effect.get_selected()][1]}}
			if kind:
				data[self.model] = {'effect': kind, **values[kind]()}
			else:
				data.pop(self.model, None)
				self.apply(self.colors)          # the static colours back on
			lightsync.save(data)

		show()
		effect.connect('notify::selected', changed)
		for w in (color, star, sky, echo, rest):
			w.connect('notify::rgba', changed)
		for w in (boost, count, speed, cycle_speed, echo_speed):
			w.connect('value-changed', changed)
		smoothing.connect('notify::active', changed)
		return card

	@staticmethod
	def _lightsync_row(text, widget):
		r = box(Gtk.Orientation.HORIZONTAL, 16)
		r.append(label(text, hexpand=True, valign=Gtk.Align.CENTER))
		r.append(widget)
		return r

	# --- drawing ------------------------------------------------------------------------

	def _scale(self, width, height):
		w, h, _keys = self.layout
		s = min(width / w, height / h)
		return s, (width - w * s) / 2, (height - h * s) / 2

	def _draw(self, _area, cr, width, height):
		s, ox, oy = self._scale(width, height)
		w, h, keys = self.layout
		if self.picture:
			cr.save()
			cr.translate(ox, oy)
			cr.scale(s * w / self.picture.get_width(), s * h / self.picture.get_height())
			Gdk.cairo_set_source_pixbuf(cr, self.picture, 0, 0)
			cr.paint_with_alpha(0.55)
			cr.restore()
		for group, kid, x, y, kw, kh in keys:
			rgb = self.colors.get(f'{group}:{kid}')
			sel = (group, kid) in self.selected
			cr.rectangle(ox + x * s + 1, oy + y * s + 1, kw * s - 2, kh * s - 2)
			if rgb:
				cr.set_source_rgba(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 0.7)
				cr.fill_preserve()
			cr.set_source_rgba(0.18, 0.55, 1.0, 1.0) if sel else cr.set_source_rgba(1, 1, 1, 0.25)
			cr.set_line_width(3 if sel else 1)
			cr.stroke()

	def _key_at(self, px, py):
		s, ox, oy = self._scale(self.area.get_width(), self.area.get_height())
		for group, kid, x, y, kw, kh in self.layout[2]:
			if ox + x * s <= px <= ox + (x + kw) * s and oy + y * s <= py <= oy + (y + kh) * s:
				return group, kid
		return None

	# --- selecting ----------------------------------------------------------------------

	def _clicked(self, _gesture, _n, x, y):
		key = self._key_at(x, y)
		if key:
			self.selected ^= {key}
			self._changed()

	def _drag_begin(self, _gesture, x, y):
		self.drag_start = (x, y)

	def _dragged(self, _gesture, dx, dy):
		x0, y0 = self.drag_start
		if math.hypot(dx, dy) < 6:
			return
		s, ox, oy = self._scale(self.area.get_width(), self.area.get_height())
		left, right = sorted((x0, x0 + dx))
		top, bottom = sorted((y0, y0 + dy))
		for group, kid, x, y, kw, kh in self.layout[2]:
			cx, cy = ox + (x + kw / 2) * s, oy + (y + kh / 2) * s
			if left <= cx <= right and top <= cy <= bottom:
				self.selected.add((group, kid))
		self._changed()

	def _select_all(self):
		self.selected = {(g, k) for g, k, *_r in self.layout[2]}
		self._changed()

	def _select(self, group, ids):
		self.selected = {(g, k) for g, k, *_r in self.layout[2] if g == group and k in ids}
		self._changed()

	def _select_none(self):
		self.selected = set()
		self._changed()

	def _changed(self):
		self.area.queue_draw()
		self._status()

	def _status(self):
		n = len(self.selected)
		self.status.set_text(f'{n} key{"s" if n != 1 else ""} selected · {len(self.colors)} coloured')

	def _paint(self):
		if not self.selected:
			return
		rgba = self.color.get_rgba()
		rgb = [round(v * 255) for v in (rgba.red, rgba.green, rgba.blue)]
		for group, kid in self.selected:
			self.colors[f'{group}:{kid}'] = rgb
		save_colors(self.model, self.colors)
		self.area.queue_draw()
		self._status()
		self.apply(self.colors)
