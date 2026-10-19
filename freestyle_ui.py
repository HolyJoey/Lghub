"""Your own key animations, like G HUB's Freestyle editor: frames painted on the per-key page, each
with a length (tenths of a second) and G HUB's easing curve into it, played in one of G HUB's
directions. Saved in G HUB's keyframe format (softlight.save_custom) and picked in LIGHTSYNC.
"""
from gi.repository import GLib, Gtk

import softlight
from ui import box, button_widget, label

PREVIEW_FPS = 25


class FreestyleCard(Gtk.Box):
	"""The Animation card; page is the PerKeyPage, whose painting goes to the selected frame while
	an animation is being edited (page.editing)."""

	def __init__(self, page):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=['card'])
		self.page = page
		self.frames = []                 # [[length, curve, colours]]
		self.current = 0
		self.loading = False
		self.timer = 0
		self.append(label('Animation', ['section-title']))
		intro = label('Make your own: paint each frame, set how long it takes to get there and how. '
		              'Saved animations show up under LIGHTSYNC.', ['muted', 'small'], wrap=True)
		intro.set_max_width_chars(60)          # a wrapping label asks for its whole line otherwise
		self.append(intro)
		self.start = button_widget('New animation from these colours', ['ghost'], self._new)
		self.append(self.start)

		self.editor = box(spacing=10)
		self.name = Gtk.Entry(placeholder_text='Name, e.g. Red pulse')
		self.editor.append(self.name)
		frames = box(Gtk.Orientation.HORIZONTAL, 8)
		self.frame_dd = Gtk.DropDown.new_from_strings(['Frame 1'])
		self.frame_dd.connect('notify::selected', self._pick)
		frames.append(self.frame_dd)
		frames.append(button_widget('Add frame', ['ghost'], self._add))
		frames.append(button_widget('Delete frame', ['ghost'], self._delete))
		self.editor.append(frames)
		self.length = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
		self.length.set_draw_value(True)
		self.length.set_hexpand(True)
		self.length.set_format_value_func(lambda _s, v: f'{v / 10:.1f} s')
		self.length.connect('value-changed', self._frame_changed)
		self.editor.append(self._row('Time to this frame', self.length))
		self.curve = Gtk.DropDown.new_from_strings([c.title() for c in softlight.CURVES])
		self.curve.connect('notify::selected', self._frame_changed)
		self.editor.append(self._row('Curve', self.curve))
		self.direction = Gtk.DropDown.new_from_strings(['Cycle', 'Reverse', 'Bounce', 'Random'])
		self.editor.append(self._row('Order', self.direction))
		buttons = box(Gtk.Orientation.HORIZONTAL, 8)
		self.play = button_widget('Preview', ['ghost'], self._preview)
		buttons.append(self.play)
		buttons.append(button_widget('Cancel', ['ghost'], self._stop_editing))
		buttons.append(button_widget('Save', ['suggested-action'], self._save))
		self.editor.append(buttons)
		self.editor.set_visible(False)
		self.append(self.editor)

	@staticmethod
	def _row(text, widget):
		r = box(Gtk.Orientation.HORIZONTAL, 16)
		r.append(label(text, hexpand=True, valign=Gtk.Align.CENTER))
		r.append(widget)
		return r

	# --- frames -----------------------------------------------------------------------------

	def colors(self):
		"""The selected frame's colours (the page paints into this dict)."""
		return self.frames[self.current][2]

	def _new(self):
		self.frames = [[10, 'LINEAR', dict(self.page.colors)]]
		self.current = 0
		self.name.set_text('')
		self.editor.set_visible(True)
		self.start.set_visible(False)
		self.page.editing = self
		self._refresh()

	def _add(self):
		length, curve, colors = self.frames[self.current]
		self.frames.insert(self.current + 1, [length, curve, dict(colors)])
		self.current += 1
		self._refresh()

	def _delete(self):
		if len(self.frames) > 1:
			del self.frames[self.current]
			self.current = min(self.current, len(self.frames) - 1)
			self._refresh()

	def _pick(self, dd, _p):
		if not self.loading and self.frames:
			self.current = dd.get_selected()
			self._refresh()

	def _frame_changed(self, *_):
		if not self.loading and self.frames:
			frame = self.frames[self.current]
			frame[0] = int(self.length.get_value())
			frame[1] = softlight.CURVES[self.curve.get_selected()]

	def _refresh(self):
		self.loading = True
		self.frame_dd.set_model(Gtk.StringList.new([f'Frame {i + 1}' for i in range(len(self.frames))]))
		self.frame_dd.set_selected(self.current)
		length, curve, _c = self.frames[self.current]
		self.length.set_value(length)
		self.curve.set_selected(softlight.CURVES.index(curve) if curve in softlight.CURVES else 0)
		self.loading = False
		self.page.area.queue_draw()

	# --- preview and save -------------------------------------------------------------------

	def _preview(self):
		if self.timer:
			self._stop_preview()
			return
		frames = [(length, curve, colors) for length, curve, colors in self.frames]
		direction = softlight.DIRECTIONS[self.direction.get_selected()]
		effect = softlight.Keyframes(frames, softlight.CUSTOM_SPEED, direction)
		start = GLib.get_monotonic_time()

		def tick():
			self.page.preview = effect.frame((GLib.get_monotonic_time() - start) / 1e6)
			self.page.area.queue_draw()
			return True

		self.timer = GLib.timeout_add(1000 // PREVIEW_FPS, tick)
		self.play.set_label('Stop')

	def _stop_preview(self):
		if self.timer:
			GLib.source_remove(self.timer)
			self.timer = 0
		self.page.preview = None
		self.play.set_label('Preview')
		self.page.area.queue_draw()

	def _stop_editing(self):
		self._stop_preview()
		self.page.editing = None
		self.editor.set_visible(False)
		self.start.set_visible(True)
		self.page.area.queue_draw()

	def _save(self):
		name = self.name.get_text().strip() or 'My animation'
		softlight.save_custom(name, [tuple(f) for f in self.frames], softlight.DIRECTIONS[self.direction.get_selected()])
		self._stop_editing()
		self.page.win.toast(f'Saved “{name}”: pick it under LIGHTSYNC (shows next time this page opens)')
