"""Surface tuning on the mouse page (HID++ 0x2240, see surface_tuning.py): pick a surface you
tuned before, or tune to the one the mouse is on. The tuning window shows G HUB's progress and
its slower / faster hint while you move the mouse."""
import threading

from gi.repository import GLib, Gtk

import surface_tuning
from ui import box, button_widget, label

HINTS = {surface_tuning.GOOD: 'Good speed, keep going',
         surface_tuning.SLOWER: 'Slower',
         surface_tuning.FASTER: 'Faster'}
FACTORY = 'Factory'


def surface_card(card, row, win, device, dev, live, info=(None, None)):
	"""The card for a mouse with 0x2240; card / row are the page's own builders, live(job) runs
	a device job on the page's worker, info = surface_tuning.info() read on that worker."""
	key = device.serial or device.id
	c = card('Surface tuning', 'Calibrates the sensor to your mouse pad: move the mouse around on '
	         'it for a few seconds. Tuned surfaces are kept, to switch back to later.')
	surfaces = surface_tuning.load(key)
	current, factory = info
	dd = Gtk.DropDown.new_from_strings([FACTORY] + [s['name'] for s in surfaces])
	dd.set_selected(next((i + 1 for i, s in enumerate(surfaces) if s['values'] == current), 0))

	def picked(w, _p):
		n = w.get_selected()
		values = surfaces[n - 1]['values'] if n > 0 else factory
		if values:
			live(lambda v=values: surface_tuning.apply(dev, v))

	dd.connect('notify::selected', picked)
	c.append(row('Surface', dd))

	def done(values):
		surfaces.append({'name': f'Surface {len(surfaces) + 1}', 'values': values})
		surface_tuning.save(key, surfaces)
		dd.set_model(Gtk.StringList.new([FACTORY] + [s['name'] for s in surfaces]))
		dd.set_selected(len(surfaces))
		win.toast('Tuned to this surface')

	c.append(row('Tune to this surface', button_widget(
		'Start', ['apply'], lambda: TuningWindow(win, device, dev, done).present())))
	return c


class TuningWindow(Gtk.Window):
	def __init__(self, parent, device, dev, on_done):
		super().__init__(title='Surface tuning', transient_for=parent, modal=True, default_width=420)
		self.dev, self.on_done = dev, on_done
		self.cancel = threading.Event()
		body = box(spacing=14, css=['page'])
		body.append(label('Move the mouse around on the pad, in circles or back and forth, until the bar '
		                  'is full.', wrap=True))
		self.bar = Gtk.ProgressBar(show_text=True)
		body.append(self.bar)
		self.hint = label('', ['muted'])
		body.append(self.hint)
		self.button = button_widget('Cancel', None, self.close)
		body.append(self.button)
		self.set_child(body)
		self.connect('close-request', self._closing)
		self.motion = surface_tuning.Motion(surface_tuning.motion_nodes(device.port))
		threading.Thread(target=self._run, daemon=True).start()

	def _closing(self, *_):
		self.cancel.set()
		return False

	def _run(self):
		try:
			self.motion.start()
			values = surface_tuning.tune(self.dev, self.motion, self._progress, self.cancel)
			GLib.idle_add(self._finished, values, None)
		except surface_tuning.Cancelled:
			pass
		except OSError as e:
			GLib.idle_add(self._finished, None, str(e))
		finally:
			self.motion.stop()

	def _progress(self, fraction, _speed, hint):
		GLib.idle_add(self._show, fraction, HINTS.get(hint, ''))

	def _show(self, fraction, hint):
		self.bar.set_fraction(fraction)
		if hint != self.hint.get_text():
			self.hint.set_text(hint)
		return False

	def _finished(self, values, error):
		if values:
			self.on_done(values)
			self.close()
		else:
			self.hint.set_text(f'Tuning stopped: {error}')
			self.button.set_label('Close')
		return False
