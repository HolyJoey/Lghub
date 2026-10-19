"""G HUB's screen sampler region editor: the screen (a grim screenshot) with the sampler's regions
on it; drag a region to move it, drag its lower-right corner to resize it. The regions are G HUB's
(its screen_sampler files); the edited rectangles are kept in lightsync.json under "regions"."""
import subprocess

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

import lightsync
from ui import box, button_widget, label

HANDLE = 14          # px: the corner that resizes
MIN_SIZE = 0.03      # a region keeps at least 3 % of the screen each way


def screenshot():
	"""The screen as a GdkPixbuf, or None without grim."""
	try:
		png = subprocess.run(['grim', '-s', '0.5', '-t', 'png', '-'], capture_output=True, timeout=10,
		                     check=True).stdout
	except (OSError, subprocess.SubprocessError):
		return None
	loader = GdkPixbuf.PixbufLoader()
	try:
		loader.write(png)
		loader.close()
	except GLib.Error:
		return None
	return loader.get_pixbuf()


def moved(rect, dx, dy, resize):
	"""A region (left, top, right, bottom as fractions) moved or resized by (dx, dy), kept on screen."""
	left, top, right, bottom = rect
	if resize:
		return [left, top, min(1.0, max(left + MIN_SIZE, right + dx)), min(1.0, max(top + MIN_SIZE, bottom + dy))]
	w, h = right - left, bottom - top
	left, top = min(1 - w, max(0.0, left + dx)), min(1 - h, max(0.0, top + dy))
	return [left, top, left + w, top + h]


class RegionEditor(Gtk.Window):
	def __init__(self, parent, model, per_key):
		super().__init__(title='Screen sampler regions', transient_for=parent, modal=True,
		                 default_width=900, default_height=620)
		self.model, self.per_key = model, per_key
		saved = lightsync.load().get(model, {}).get('regions', {})
		self.regions = {rid: (name, list(saved.get(rid, rect))) for rid, (name, rect)
		                in lightsync.sampler_regions(per_key).items()}
		self.picture = screenshot()
		self.drag = None             # (region id, resize, start rect)
		body = box(spacing=12, css=['page'])
		body.append(label('Drag a region to move it, its lower-right corner to resize it.', ['muted'], wrap=True))
		self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
		self.area.set_draw_func(self._draw)
		gesture = Gtk.GestureDrag()
		gesture.connect('drag-begin', self._begin)
		gesture.connect('drag-update', self._update)
		gesture.connect('drag-end', lambda *_: setattr(self, 'drag', None))
		self.area.add_controller(gesture)
		body.append(self.area)
		buttons = box(Gtk.Orientation.HORIZONTAL, 10)
		buttons.append(button_widget('G HUB’s regions', ['ghost'], self._reset))
		buttons.append(button_widget('Save', ['suggested-action'], self._save))
		body.append(buttons)
		if not self.regions:
			body.append(label('G HUB’s sampler regions aren’t downloaded yet: turn the screen sampler on once, '
			                  'then open this again.', ['muted'], wrap=True))
		self.set_child(body)

	def _frame(self):
		"""(x, y, width, height) of the screen picture inside the drawing area."""
		w, h = self.area.get_width(), self.area.get_height()
		ratio = (self.picture.get_width() / self.picture.get_height()) if self.picture else 16 / 9
		pw, ph = (w, w / ratio) if w / ratio <= h else (h * ratio, h)
		return (w - pw) / 2, (h - ph) / 2, pw, ph

	def _draw(self, _area, cr, _w, _h):
		x, y, pw, ph = self._frame()
		if self.picture:
			cr.save()
			cr.translate(x, y)
			cr.scale(pw / self.picture.get_width(), ph / self.picture.get_height())
			Gdk.cairo_set_source_pixbuf(cr, self.picture, 0, 0)
			cr.paint()
			cr.restore()
		else:
			cr.set_source_rgb(0.15, 0.15, 0.18)
			cr.rectangle(x, y, pw, ph)
			cr.fill()
		for name, (left, top, right, bottom) in self.regions.values():
			rx, ry, rw, rh = x + left * pw, y + top * ph, (right - left) * pw, (bottom - top) * ph
			cr.set_source_rgba(0.2, 0.55, 1.0, 0.25)
			cr.rectangle(rx, ry, rw, rh)
			cr.fill()
			cr.set_source_rgba(0.2, 0.55, 1.0, 1.0)
			cr.set_line_width(2)
			cr.rectangle(rx, ry, rw, rh)
			cr.stroke()
			cr.rectangle(rx + rw - HANDLE, ry + rh - HANDLE, HANDLE, HANDLE)
			cr.fill()
			cr.set_source_rgb(1, 1, 1)
			cr.move_to(rx + 6, ry + 18)
			cr.show_text(name.replace('_', ' ').title())

	def _hit(self, px, py):
		x, y, pw, ph = self._frame()
		for rid, (_name, (left, top, right, bottom)) in reversed(list(self.regions.items())):
			rx, ry, rx2, ry2 = x + left * pw, y + top * ph, x + right * pw, y + bottom * ph
			if rx <= px <= rx2 and ry <= py <= ry2:
				return rid, px >= rx2 - HANDLE and py >= ry2 - HANDLE
		return None, False

	def _begin(self, _g, px, py):
		rid, resize = self._hit(px, py)
		self.drag = (rid, resize, list(self.regions[rid][1])) if rid else None

	def _update(self, _g, dx, dy):
		if not self.drag:
			return
		rid, resize, start = self.drag
		_x, _y, pw, ph = self._frame()
		self.regions[rid] = (self.regions[rid][0], moved(start, dx / pw, dy / ph, resize))
		self.area.queue_draw()

	def _reset(self):
		self.regions = dict(lightsync.sampler_regions(self.per_key))
		self.regions = {rid: (name, list(rect)) for rid, (name, rect) in self.regions.items()}
		self.area.queue_draw()

	def _save(self):
		data = lightsync.load()
		settings = data.get(self.model, {'effect': 'screen'})
		settings['regions'] = {rid: [round(v, 4) for v in rect] for rid, (_n, rect) in self.regions.items()}
		data[self.model] = settings
		lightsync.save(data)
		self.close()
