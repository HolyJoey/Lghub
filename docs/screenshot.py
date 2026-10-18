"""Render one page of the app to a PNG, for the README. Used by docs/screenshots.sh.

  screenshot.py <start page> <sub page or -> <out.png> [wait ms]

The window draws itself (no screen capture), with animations off so page switches are done
when the picture is taken.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
page, sub, out = sys.argv[1:4]
wait = int(sys.argv[4]) if len(sys.argv) > 4 else 3000
sys.argv = ['app.py', '--page', page]

import app  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

application = app.App()
application.connect('startup', lambda *_: Gtk.Settings.get_default().set_property('gtk-enable-animations', False))


def open_sub_page():
	win = application.props.active_window
	if sub != '-':
		view = win.device_view if win.stack.get_visible_child_name() == 'device' else win.blue_voice
		view.show_page(sub)
	GLib.timeout_add(800, shoot)
	return False


def shoot():
	win = application.props.active_window
	paintable = Gtk.WidgetPaintable.new(win)
	snapshot = Gtk.Snapshot()
	paintable.snapshot(snapshot, win.get_width(), win.get_height())
	node = snapshot.to_node()
	if node is None:
		return True   # not drawn yet; try again
	win.get_renderer().render_texture(node, None).save_to_png(out)
	application.quit()
	return False


GLib.timeout_add(wait, open_sub_page)
application.run(None)
