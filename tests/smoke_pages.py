"""Opens every page of the real window for every simulated device, and every sub-page of each, then
quits. Exit status = the number of Python errors raised (also inside GTK callbacks). Run by
test_smoke_pages.py with LGHUB_FAKE_DEVICES set and a display (GDK_BACKEND=broadway works)."""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.argv = ['app.py', '--page', 'home']

import app  # noqa: E402
import devices  # noqa: E402
from gi.repository import Gio, GLib, Gtk  # noqa: E402

errors = []


def record(kind, value, tb):
	errors.append(''.join(traceback.format_exception(kind, value, tb)))
	sys.stderr.write('SMOKE-ERROR ' + errors[-1])


sys.excepthook = record
application = app.App()
application.set_flags(application.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)   # beside a running Lghub
application.connect('startup', lambda *_: Gtk.Settings.get_default().set_property('gtk-enable-animations', False))
STEP_MS = int(os.environ.get('SMOKE_STEP_MS', '1500'))


def steps():
	win = application.props.active_window
	yield
	win.show_games()
	yield
	win.show_settings()
	yield
	win.show_device(None)                     # the headset view without a headset
	for key in list(getattr(win.blue_voice, 'nav_buttons', {})):
		win.blue_voice.show_page(key)
		yield
	for device in devices.discover():
		win.show_device(device)
		yield
		yield                                 # pages fill in from a worker thread
		view = win.device_view if win.stack.get_visible_child_name() == 'device' else win.blue_voice
		for key in list(getattr(view, 'nav_buttons', {})):
			view.show_page(key)
			sys.stderr.write(f'SMOKE-PAGE {device.usb_id} {key}\n')
			yield
		win.show_home()
		yield


walk = steps()


def step():
	try:
		next(walk)
	except StopIteration:
		application.quit()
		return False
	except Exception:                         # noqa: BLE001 - recorded, then the walk goes on
		record(*sys.exc_info())
	return True


GLib.timeout_add(STEP_MS, step)
application.run(None)
sys.exit(min(len(errors), 100))
