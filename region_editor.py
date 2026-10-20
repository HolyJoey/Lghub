"""G HUB's screen sampler region editor: the screen (a grim screenshot, or a picture of your own)
with the sampler's regions on it; drag a region to move it, drag its lower-right corner to resize
it. As in G HUB's sample editor: add regions (a centred box, inset 0.4 from each edge), delete the
selected one (Delete key or button, while more than one is left; its keys go to the background),
rename it, and give keys (or zones) to the selected region: click a key to give it to the region,
click it again to take it back (G HUB's rule). The regions start as G HUB's (its screen_sampler
files); the edits are kept in lightsync.json ("regions", "region_names", "assign")."""
import subprocess
import uuid

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

import lightsync
from ui import box, button_widget, label

HANDLE = 14          # px: the corner that resizes
MIN_SIZE = 0.03      # a region keeps at least 3 % of the screen each way
NEW_INSET = 0.4      # G HUB's new sample: left = right = top = bottom = 0.4


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


def new_region(regions):
	"""(id, [name, rect]) of a region added the way G HUB adds one ("Sample n" is our wording of its
	SAMPLE_DEFAULT_NAME string)."""
	return str(uuid.uuid4()), [f'Sample {len(regions) + 1}', [NEW_INSET, NEW_INSET, 1 - NEW_INSET, 1 - NEW_INSET]]


def toggled(keys, key, region):
	"""The key map after clicking a key with a region selected: G HUB gives the key to the region,
	or back to the background when it already had it."""
	out = dict(keys)
	out[key] = lightsync.BACKGROUND if keys.get(key) == region else region
	return out


def deleted(regions, keys, region):
	"""(regions, keys) without one region; its keys go to the background (G HUB's deletedRegion)."""
	return ({r: v for r, v in regions.items() if r != region},
	        {k: lightsync.BACKGROUND if r == region else r for k, r in keys.items()})


def changes(ghub_keys, keys):
	"""The keys whose region differs from G HUB's map (what is saved as "assign")."""
	return {k: r for k, r in keys.items() if ghub_keys.get(k) != r}


def shown_name(name):
	"""G HUB's region names (MID_LEFT) as words; names you gave are kept as typed."""
	return name.replace('_', ' ').title() if name.isupper() else name


def color_of(index):
	"""A region's colour in the editor (ours)."""
	hues = ((0.2, 0.55, 1.0), (1.0, 0.45, 0.2), (0.3, 0.85, 0.4), (0.9, 0.3, 0.8), (1.0, 0.85, 0.2),
	        (0.3, 0.9, 0.9), (0.95, 0.3, 0.35), (0.6, 0.5, 1.0))
	return hues[index % len(hues)]


class RegionEditor(Gtk.Window):
	def __init__(self, parent, model, per_key):
		super().__init__(title='Screen sampler regions', transient_for=parent, modal=True,
		                 default_width=900, default_height=720)
		self.model, self.per_key = model, per_key
		self.ghub, self.ghub_keys = lightsync.sampler_regions(per_key)
		self._load(lightsync.load().get(model, {}))
		self.layout = None
		if per_key:
			import perkey
			self.layout = perkey.load_layout(model)
		self.picture = screenshot()
		self.selected = None
		self.drag = None             # (region id, resize, start rect)
		body = box(spacing=12, css=['page'])
		body.append(label('Drag a region to move it, its lower-right corner to resize it. Select a region, then '
		                  'click keys to give them to it (again to take them back).', ['muted'], wrap=True))
		self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
		self.area.set_draw_func(self._draw)
		gesture = Gtk.GestureDrag()
		gesture.connect('drag-begin', self._begin)
		gesture.connect('drag-update', self._update)
		gesture.connect('drag-end', lambda *_: setattr(self, 'drag', None))
		self.area.add_controller(gesture)
		body.append(self.area)
		body.append(self._region_row())
		self.assign = self._assign_widget()
		if self.assign:
			body.append(self.assign)
		buttons = box(Gtk.Orientation.HORIZONTAL, 10)
		buttons.append(button_widget('Take screenshot', ['ghost'], self._screenshot))
		buttons.append(button_widget('Custom background', ['ghost'], self._background))
		buttons.append(button_widget('G HUB’s regions', ['ghost'], self._reset))
		buttons.append(button_widget('Save', ['suggested-action'], self._save))
		body.append(buttons)
		if not self.regions:
			body.append(label('G HUB’s sampler regions aren’t downloaded yet: turn the screen sampler on once, '
			                  'then open this again.', ['muted'], wrap=True))
		keys = Gtk.EventControllerKey()
		keys.connect('key-pressed', self._key)
		self.add_controller(keys)
		self.set_child(body)
		self._select(None)

	def _load(self, settings):
		"""Regions {id: [name, rect]} and keys {key or zone: region} from G HUB's plus saved edits."""
		rects, self.keys = lightsync.edit_sampler({rid: rect for rid, (_n, rect) in self.ghub.items()},
		                                          self.ghub_keys, settings)
		names = {**{rid: name for rid, (name, _r) in self.ghub.items()}, **settings.get('region_names', {})}
		self.regions = {rid: [names.get(rid, rid), list(rect)] for rid, rect in rects.items()}

	# --- the selected region ----------------------------------------------------------------

	def _region_row(self):
		row = box(Gtk.Orientation.HORIZONTAL, 10)
		self.name = Gtk.Entry(placeholder_text='Region name', hexpand=True)
		self.name.connect('changed', self._renamed)
		row.append(self.name)
		row.append(button_widget('Add region', ['ghost'], self._add))
		self.delete = button_widget('Delete region', ['ghost'], self._delete)
		row.append(self.delete)
		return row

	def _select(self, rid):
		self.selected = rid
		self.name.set_sensitive(rid is not None)
		self.name.set_text(shown_name(self.regions[rid][0]) if rid else '')
		self.delete.set_sensitive(rid is not None and len(self.regions) > 1)
		if self.assign:
			self.assign.queue_draw() if self.layout else self._refresh_zones()
		self.area.queue_draw()

	def _renamed(self, entry):
		text = entry.get_text().strip()
		if self.selected and text and text != shown_name(self.regions[self.selected][0]):
			self.regions[self.selected][0] = text
			self.area.queue_draw()

	def _add(self):
		rid, region = new_region(self.regions)
		self.regions[rid] = region
		self._select(rid)

	def _delete(self):
		if self.selected and len(self.regions) > 1:
			self.regions, self.keys = deleted(self.regions, self.keys, self.selected)
			self._select(None)

	def _key(self, _c, keyval, _code, _state):
		if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and not self.name.has_focus():
			self._delete()
			return True
		return False

	# --- keys / zones -----------------------------------------------------------------------

	def _assign_widget(self):
		if self.layout:
			keyboard = Gtk.DrawingArea(hexpand=True)
			keyboard.set_size_request(-1, 200)
			keyboard.set_draw_func(self._draw_keys)
			click = Gtk.GestureClick()
			click.connect('pressed', self._key_clicked)
			keyboard.add_controller(click)
			return keyboard
		if not self.per_key and self.keys:
			self.zone_rows = box(spacing=6)
			self._refresh_zones()
			return self.zone_rows
		return None

	def _refresh_zones(self):
		"""One dropdown per lighting zone in G HUB's file: the region it takes."""
		while child := self.zone_rows.get_first_child():
			self.zone_rows.remove(child)
		ids = list(self.regions) + [lightsync.BACKGROUND]
		for zone in sorted(self.keys):
			dd = Gtk.DropDown.new_from_strings([shown_name(self.regions[r][0]) for r in self.regions] + ['Off'])
			current = self.keys[zone]
			dd.set_selected(ids.index(current) if current in ids else len(ids) - 1)
			dd.connect('notify::selected', lambda d, _p, z=zone: self.keys.__setitem__(z, ids[d.get_selected()]))
			row = box(Gtk.Orientation.HORIZONTAL, 16)
			row.append(label(zone.replace('ZONE_', '').replace('_', ' ').title(), hexpand=True, valign=Gtk.Align.CENTER))
			row.append(dd)
			self.zone_rows.append(row)

	def _key_scale(self, width, height):
		w, h, _keys = self.layout
		s = min(width / w, height / h)
		return s, (width - w * s) / 2, (height - h * s) / 2

	def _draw_keys(self, _area, cr, width, height):
		s, ox, oy = self._key_scale(width, height)
		order = list(self.regions)
		for group, kid, x, y, kw, kh in self.layout[2]:
			rid = self.keys.get(f'{group}:{kid}')
			cr.rectangle(ox + x * s + 1, oy + y * s + 1, kw * s - 2, kh * s - 2)
			if rid in self.regions:
				r, g, b = color_of(order.index(rid))
				cr.set_source_rgba(r, g, b, 0.9 if rid == self.selected else 0.35)
				cr.fill_preserve()
			cr.set_source_rgba(1, 1, 1, 0.25)
			cr.set_line_width(1)
			cr.stroke()

	def _key_clicked(self, gesture, _n, px, py):
		if not self.selected:
			return
		area = gesture.get_widget()
		s, ox, oy = self._key_scale(area.get_width(), area.get_height())
		for group, kid, x, y, kw, kh in self.layout[2]:
			if ox + x * s <= px <= ox + (x + kw) * s and oy + y * s <= py <= oy + (y + kh) * s:
				self.keys = toggled(self.keys, f'{group}:{kid}', self.selected)
				area.queue_draw()
				return

	# --- the screen -------------------------------------------------------------------------

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
		for i, (rid, (name, (left, top, right, bottom))) in enumerate(self.regions.items()):
			r, g, b = color_of(i)
			rx, ry, rw, rh = x + left * pw, y + top * ph, (right - left) * pw, (bottom - top) * ph
			cr.set_source_rgba(r, g, b, 0.25)
			cr.rectangle(rx, ry, rw, rh)
			cr.fill()
			cr.set_source_rgba(r, g, b, 1.0)
			cr.set_line_width(4 if rid == self.selected else 2)
			cr.rectangle(rx, ry, rw, rh)
			cr.stroke()
			cr.rectangle(rx + rw - HANDLE, ry + rh - HANDLE, HANDLE, HANDLE)
			cr.fill()
			cr.set_source_rgb(1, 1, 1)
			cr.move_to(rx + 6, ry + 18)
			cr.show_text(shown_name(name))

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
		if rid != self.selected:
			self._select(rid)

	def _update(self, _g, dx, dy):
		if not self.drag:
			return
		rid, resize, start = self.drag
		_x, _y, pw, ph = self._frame()
		self.regions[rid][1] = moved(start, dx / pw, dy / ph, resize)
		self.area.queue_draw()

	def _screenshot(self):
		self.picture = screenshot() or self.picture
		self.area.queue_draw()

	def _background(self):
		"""G HUB's custom background: any picture to place the regions on."""
		dialog = Gtk.FileDialog(title='Background picture')
		images = Gtk.FileFilter(name='Pictures')
		images.add_pixbuf_formats()
		filters = Gio.ListStore.new(Gtk.FileFilter)
		filters.append(images)
		dialog.set_filters(filters)

		def chosen(d, result):
			try:
				self.picture = GdkPixbuf.Pixbuf.new_from_file(d.open_finish(result).get_path())
			except GLib.Error:
				return
			self.area.queue_draw()

		dialog.open(self, None, chosen)

	def _reset(self):
		self._load({})
		self._select(None)

	def _save(self):
		data = lightsync.load()
		settings = data.get(self.model, {'effect': 'screen'})
		settings['regions'] = {rid: [round(v, 4) for v in rect] for rid, (_n, rect) in self.regions.items()}
		ghub_names = {rid: name for rid, (name, _r) in self.ghub.items()}
		settings['region_names'] = {rid: name for rid, (name, _r) in self.regions.items() if ghub_names.get(rid) != name}
		settings['assign'] = changes(self.ghub_keys, self.keys)
		data[self.model] = settings
		lightsync.save(data)
		self.close()
