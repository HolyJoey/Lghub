"""The webcam page: a live preview and every picture control the camera offers, grouped like
G HUB's."""
import os
import threading

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

import v4l2
import webcam
from ui import NOTIFY_ACTIVE, box, button_widget, device_icon, device_sidebar, label, nav_button, page_header, scrolled
from worker import Worker

PREVIEW_HEIGHT = 300
GROUPS = (
	('Picture', ('brightness', 'contrast', 'saturation', 'sharpness', 'gamma', 'hue', 'gain', 'backlight')),
	('White balance', ('white_balance',)),
	('Exposure', ('exposure', 'auto_exposure', 'iris')),
	('Focus and zoom', ('focus', 'zoom', 'pan', 'tilt')),
)
NICE_NAMES = {'white_balance_automatic': 'Automatic', 'white_balance_temperature': 'Temperature (K)',
              'auto_exposure': 'Mode', 'exposure_time_absolute': 'Exposure time',
              'exposure_dynamic_framerate': 'Lower frame rate in low light', 'focus_automatic_continuous': 'Autofocus',
              'focus_absolute': 'Focus', 'zoom_absolute': 'Zoom', 'pan_absolute': 'Pan', 'tilt_absolute': 'Tilt',
              'power_line_frequency': 'Anti-flicker (mains frequency)', 'backlight_compensation': 'Backlight compensation'}


def group_of(ctrl):
	for title, prefixes in GROUPS:
		if any(ctrl.key.startswith(p) for p in prefixes):
			return title
	return 'Other'


class WebcamView(Gtk.Box):
	def __init__(self, win, device):
		super().__init__(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
		self.win = win
		self.device = device
		self.camera = None
		self.loading = False
		self.widgets = {}        # control id -> (control, widget, row)
		self.worker = Worker()

		icon = device_icon(device, 32)
		side = device_sidebar(win.show_home, icon, device.name, device.type_name)
		nav = box(spacing=4)
		picture = nav_button('Picture', 'camera-photo-symbolic', lambda: None)
		picture.add_css_class('active')
		nav.append(picture)
		side.append(nav)
		side.append(box(vexpand=True))
		info = box(spacing=6, css=['card'])
		info.append(label('Settings stick', ['muted', 'small']))
		info.append(label('Lghub puts them back whenever the camera is plugged in.', ['small'], wrap=True,
		                  max_width_chars=24))
		side.append(info)
		self.append(side)

		self.page = box(spacing=20, css=['page'])
		self.page.append(page_header('Picture', 'Changes show right away in any app using the camera.',
		                             button_widget('Reset all', ['ghost'], self._reset)))
		self.page.append(self._preview_card())
		self.body = box(spacing=20)
		self.body.append(label('Opening the camera…', ['muted']))
		self.page.append(self.body)
		self.append(scrolled(self.page))
		self.worker.submit(self._open, self._show, self._failed)

	def close(self):
		self._stop_preview()
		cam = self.camera
		self.worker.submit(lambda: cam and cam.close())
		self.worker.stop()

	# --- preview --------------------------------------------------------------------------

	def _preview_card(self):
		c = box(spacing=12, css=['card'])
		head = box(Gtk.Orientation.HORIZONTAL, 12)
		head.append(label('Preview', ['section-title'], hexpand=True, valign=Gtk.Align.CENTER))
		# LGHUB_PREVIEW=0 starts with the preview off (docs/screenshots.sh: no faces in the README)
		self.preview_switch = Gtk.Switch(active=os.environ.get('LGHUB_PREVIEW') != '0', valign=Gtk.Align.CENTER)
		self.preview_switch.connect(NOTIFY_ACTIVE, lambda w, _p: self._start_preview() if w.get_active()
		                            else self._stop_preview())
		self.preview_switch.connect(NOTIFY_ACTIVE, lambda w, _p: self.picture.set_visible(w.get_active()))
		head.append(self.preview_switch)
		c.append(head)
		self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, height_request=PREVIEW_HEIGHT,
		                           visible=self.preview_switch.get_active())
		c.append(self.picture)
		self.preview_note = label('', ['muted', 'small'], wrap=True)
		c.append(self.preview_note)
		self.streaming = None        # the thread's stop event while the preview runs
		self.frame_pending = False
		return c

	def _start_preview(self):
		if self.streaming or not self.camera or not self.preview_switch.get_active():
			return
		stop = threading.Event()
		self.streaming = stop
		self.preview_note.set_text('')
		threading.Thread(target=self._stream, args=(self.camera, stop), daemon=True).start()

	def _stop_preview(self):
		if self.streaming:
			self.streaming.set()
			self.streaming = None

	def _stream(self, camera, stop):
		try:
			stream = v4l2.Stream(camera)
		except OSError as e:
			text = ('The camera is in use by another app, so there is no preview here. Settings still work.'
			        if e.errno == 16 else f'No preview: {e.strerror or e}.')
			GLib.idle_add(lambda: self.preview_note.set_text(text) and False)
			return
		try:
			while not stop.is_set():
				data = stream.frame()
				if data and not self.frame_pending:
					self.frame_pending = True
					GLib.idle_add(self._show_frame, data)
		except OSError:
			GLib.idle_add(lambda: self.preview_note.set_text('The preview stopped.') and False)
		finally:
			stream.close()

	def _show_frame(self, data):
		self.frame_pending = False
		loader = GdkPixbuf.PixbufLoader.new_with_type('jpeg')
		try:
			loader.write(data)
			loader.close()
			self.picture.set_paintable(Gdk.Texture.new_for_pixbuf(loader.get_pixbuf()))
		except GLib.Error:
			pass   # a damaged frame; the next one will do

	def _open(self):
		node = v4l2.video_node(self.device.id.split(':', 1)[1])
		if not node:
			raise OSError('no video device for this camera')
		self.camera = v4l2.Camera(node)
		return self.camera.controls()

	def _failed(self, error):
		self._clear()
		self.body.append(label(f'Can’t open the camera: {error}.', ['muted'], wrap=True))

	def _clear(self):
		while (child := self.body.get_first_child()):
			self.body.remove(child)

	def _show(self, controls):
		self._start_preview()
		self._clear()
		self.widgets = {}
		self.loading = True
		cards = {}
		for title in [g for g, _ in GROUPS] + ['Other']:
			c = box(spacing=12, css=['card'])
			c.append(label(title, ['section-title']))
			cards[title] = c
		for ctrl in controls:
			cards[group_of(ctrl)].append(self._row(ctrl))
		for c in cards.values():
			if c.get_first_child().get_next_sibling():
				self.body.append(c)
		if not controls:
			self.body.append(label('This camera has no adjustable settings.', ['muted']))
		self.loading = False

	def _row(self, ctrl):
		r = box(Gtk.Orientation.HORIZONTAL, 14)
		r.append(label(NICE_NAMES.get(ctrl.key, ctrl.name), ['muted'], width_chars=26, wrap=True))
		if ctrl.kind == v4l2.T_BOOLEAN:
			widget = Gtk.Switch(active=bool(ctrl.value), valign=Gtk.Align.CENTER, halign=Gtk.Align.END, hexpand=True)
			widget.connect(NOTIFY_ACTIVE, lambda w, _p, c=ctrl: self._set(c, int(w.get_active())))
		elif ctrl.menu:
			values = list(ctrl.menu)
			widget = Gtk.DropDown.new_from_strings([ctrl.menu[v] for v in values])
			widget.set_selected(values.index(ctrl.value) if ctrl.value in values else 0)
			widget.set_hexpand(True)
			widget.set_halign(Gtk.Align.END)
			widget.connect('notify::selected', lambda w, _p, c=ctrl, v=values: self._set(c, v[w.get_selected()]))
		else:
			widget = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, ctrl.low, ctrl.high, ctrl.step)
			widget.set_value(ctrl.value)
			widget.set_hexpand(True)
			widget.set_draw_value(False)
			shown = label(str(ctrl.value), ['value'], width_chars=6, xalign=1.0)
			widget.connect('value-changed', lambda w, c=ctrl, s=shown: self._on_scale(c, w, s))
			r.append(widget)
			widget.add_mark(ctrl.default, Gtk.PositionType.BOTTOM, None)
			r.append(shown)
			self._state(r, ctrl)
			self.widgets[ctrl.id] = (ctrl, widget, r)
			return r
		r.append(widget)
		self._state(r, ctrl)
		self.widgets[ctrl.id] = (ctrl, widget, r)
		return r

	@staticmethod
	def _state(r, ctrl):
		r.set_sensitive(not (ctrl.inactive or ctrl.read_only))
		r.set_tooltip_text('Set by the automatic mode' if ctrl.inactive else None)

	def _on_scale(self, ctrl, scale, shown):
		value = int(round(scale.get_value() / ctrl.step) * ctrl.step)
		shown.set_text(str(value))
		self._set(ctrl, value)

	def _set(self, ctrl, value):
		if self.loading or value == ctrl.value:
			return
		ctrl.value = value
		cam = self.camera
		webcam.remember(self.device, ctrl.key, value)
		refresh = ctrl.kind != v4l2.T_INTEGER     # auto modes enable or disable other controls
		self.worker.submit(lambda: (cam.set(ctrl.id, value), cam.controls() if refresh else None)[1],
		                   self._after_set, lambda e: self.win.toast(f'The camera refused: {e}'))

	def _after_set(self, controls):
		if not controls:
			return
		self.loading = True
		for c in controls:
			if c.id in self.widgets:
				old, widget, r = self.widgets[c.id]
				old.flags = c.flags
				self._state(r, c)
				if c.value != old.value and isinstance(widget, Gtk.Scale):
					old.value = c.value
					widget.set_value(c.value)
		self.loading = False

	def _reset(self):
		cam = self.camera
		if not cam:
			return
		webcam.forget(self.device)

		def job():
			defaults = {c.key: c.default for c in cam.controls()}
			webcam.apply(cam, defaults)
			return cam.controls()
		self.worker.submit(job, self._show, lambda e: self.win.toast(f'The camera refused: {e}'))
		self.win.toast('Back to the camera’s defaults')
