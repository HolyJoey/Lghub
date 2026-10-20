"""The window's side of updates (update.py): a banner on the home page when a newer release is out,
its notes and Update now, progress, and the Updates card on the Settings page. Ours."""
import os
import sys

from gi.repository import Adw, GLib, Gtk

import store
import update
from version import VERSION
from worker import Worker

RELEASES = f'https://github.com/{update.REPO}/releases'


class UpdateBanner:
	"""The home page's update banner (an Adw.Banner, which can't be subclassed: .widget)."""

	def __init__(self, win):
		self.widget = Adw.Banner(revealed=False, visible=False, button_label='What’s new…')
		self.win = win
		self.info = None
		self.busy = False
		self.worker = Worker()
		self.widget.connect('button-clicked', lambda _b: self._details())

	def refresh(self):
		"""Shows the banner when the last check found a newer release (cheap: one small file)."""
		if self.busy:
			return
		info = update.pending()
		if info != self.info:
			self.info = info
			if info:
				self.widget.set_title(f'Lghub {info["version"]} is available')
			self.widget.set_visible(bool(info))   # hidden, it takes no room in the page's spacing
			self.widget.set_revealed(bool(info))

	def _details(self):
		if not self.info:
			return
		notes = self.info['notes'].strip() or 'No notes for this release.'
		dialog = Adw.AlertDialog(heading=f'Lghub {self.info["version"]}', body=notes[:2000])
		dialog.add_response('cancel', 'Later')
		if update.can_install():
			dialog.add_response('update', 'Update now')
			dialog.set_response_appearance('update', Adw.ResponseAppearance.SUGGESTED)
			dialog.connect('response', lambda _d, r: r == 'update' and self._install())
		else:
			dialog.set_body(notes[:2000] + '\n\nThis copy of Lghub isn’t updated by the app (it runs from a git checkout '
			                'or a package): update it the way you installed it.')
			dialog.add_response('open', 'Open releases')
			dialog.connect('response', lambda _d, r: r == 'open' and Gtk.UriLauncher.new(RELEASES).launch(self.win, None))
		dialog.present(self.win)

	def _install(self):
		self.busy = True
		self.widget.set_button_label('')
		info = self.info

		def progress(text):
			GLib.idle_add(self.widget.set_title, f'{text} Lghub {info["version"]}…')
		self.worker.submit(lambda: update.install(info, progress), self._done, self._failed)

	def _done(self, _output):
		self.widget.set_title(f'Updated to {self.info["version"]}. Restarting…')
		GLib.timeout_add(1200, _restart)

	def _failed(self, error):
		self.busy = False
		self.widget.set_button_label('What’s new…')
		self.widget.set_title(f'Lghub {self.info["version"]} is available')
		if isinstance(error, update.NeedsRoot):
			body = ('The new version needs something only an administrator can install. Nothing was changed. '
			        f'Run its installer in a terminal:\n\ncd {error.folder} && ./install.sh')
		elif isinstance(error, RuntimeError):
			body = 'The installer stopped; the previous version was put back.'
		else:
			body = f'Nothing was changed: {error}.'
		dialog = Adw.AlertDialog(heading='Update didn’t finish', body=body)
		dialog.add_response('ok', 'OK')
		output = getattr(error, 'output', None) or (str(error) if isinstance(error, RuntimeError) else '')
		if output:
			view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
			view.get_buffer().set_text(output[-4000:])
			scroller = Gtk.ScrolledWindow(min_content_height=200, child=view)
			expander = Gtk.Expander(label='Details', child=scroller)
			dialog.set_extra_child(expander)
		dialog.present(self.win)


def _restart():
	"""Starts the window again from the newly installed files."""
	os.execv(sys.executable, [sys.executable] + sys.argv)


def settings_card(banner):
	"""Settings: the version, the daily check switch and Check now."""
	from settings_ui import _row, _switch
	from ui import box, button_widget, label
	c = box(spacing=12, css=['card'])
	c.append(label('Updates', ['section-title']))
	c.append(_row('Check for updates', _switch('check_updates'),
	              f'Once a day, asks GitHub for the newest Lghub release (nothing else is sent). This is {VERSION}.'))
	status = label('', ['muted', 'small'], wrap=True)
	worker = Worker()

	def checked(info):
		status.set_text(f'Lghub {info["version"]} is available: see the banner on the Devices page.' if info
		                else f'{VERSION} is the newest release.')
		banner.refresh()

	def check():
		status.set_text('Checking…')
		worker.submit(update.check, checked, lambda e: status.set_text(f'Couldn’t check: {e}'))
	c.append(_row('Newest release', button_widget('Check now', ['ghost'], check)))
	c.append(status)
	if not store.load_config().get('check_updates', True):
		status.set_text('Daily checks are off.')
	return c
