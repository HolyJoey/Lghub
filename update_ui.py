"""The window's side of updates (update.py): a banner on the home page when a newer release is out,
its notes and Update now, progress, and the Updates card on the Settings page. Ours."""
import os
import re
import sys

from gi.repository import Adw, GLib, Gtk

import store
import update
from version import VERSION
from worker import Worker

RELEASES = f'https://github.com/{update.REPO}/releases'


def notes_blocks(text):
	"""[(kind, Pango markup)] for release notes written in simple Markdown: 'p' paragraphs (**bold**
	lines), 'li' "- " bullets, 'gap' blank lines; hard-wrapped lines are joined back."""
	blocks = []                 # [(kind, text)]: 'p' paragraph, 'li' bullet
	for line in text.strip().splitlines():
		line = line.strip()
		if not line:
			blocks.append(('gap', ''))
		elif line.startswith(('- ', '* ')):
			blocks.append(('li', line[2:]))
		elif blocks and blocks[-1][0] in ('li', 'p') and not line.startswith('**'):
			blocks[-1] = (blocks[-1][0], f'{blocks[-1][1]} {line}')
		else:
			blocks.append(('p', line))
	return [(kind, re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', GLib.markup_escape_text(body))) for kind, body in blocks]


def notes_view(text):
	"""The notes as a left-aligned, scrollable block for a dialog; bullets hang."""
	column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
	for kind, markup in notes_blocks(text):
		if kind == 'gap':
			column.append(Gtk.Box(height_request=6))
			continue
		label = Gtk.Label(use_markup=True, wrap=True, xalign=0, hexpand=True, label=markup)
		if kind == 'li':
			line = Gtk.Box(spacing=8)
			line.append(Gtk.Label(label='•', yalign=0, margin_start=4))
			line.append(label)
			column.append(line)
		else:
			column.append(label)
	scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
	                              max_content_height=360)
	scroller.set_child(column)
	scroller.set_size_request(460, -1)
	return scroller


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
		notes = self.info['notes'].strip()[:4000] or 'No notes for this release.'
		dialog = Adw.AlertDialog(heading=f'Lghub {self.info["version"]}', extra_child=notes_view(notes))
		dialog.set_prefer_wide_layout(True)
		dialog.add_response('cancel', 'Later')
		if update.can_install():
			dialog.add_response('update', 'Update now')
			dialog.set_response_appearance('update', Adw.ResponseAppearance.SUGGESTED)
			dialog.connect('response', lambda _d, r: r == 'update' and self._install())
		else:
			dialog.set_body('This copy of Lghub isn’t updated by the app (it runs from a git checkout '
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
