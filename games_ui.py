"""Games: per-game profiles (profiles.py). Add a game by its executable or its Steam App ID; it
gets the settings as they are now, and the engine switches to them while the game runs."""
from gi.repository import GLib, Gtk

import profiles
import store
from ui import box, button_widget, label, page_header


class GamesPage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.win = win
		self.active = None
		self.append(page_header('Games', 'Settings that switch on while a game runs and back when it closes: '
		                        'Blue VO!CE, equalizer and surround.',
		                        button_widget('Devices', ['ghost'], win.show_home)))

		add = box(spacing=10, css=['card'])
		add.append(label('Add a game', ['section-title']))
		add.append(label('It starts with the settings you have now; change them while the game runs and '
		                 'they stay with the game.', ['muted', 'small'], wrap=True))
		self.name = Gtk.Entry(placeholder_text='Name, e.g. Elden Ring')
		self.exe = Gtk.Entry(placeholder_text='Executable, e.g. eldenring.exe (Proton games too)')
		self.steam = Gtk.Entry(placeholder_text='or Steam App ID, e.g. 1245620')
		for e in (self.name, self.exe, self.steam):
			add.append(e)
		add.append(button_widget('Add with current settings', ['suggested-action'], self._add))
		self.append(add)

		self.list = box(spacing=12)
		self.append(self.list)
		self.refresh()
		self._timer = GLib.timeout_add_seconds(2, self._poll)

	def refresh(self):
		while (child := self.list.get_first_child()):
			self.list.remove(child)
		data = profiles.load()
		if not data['profiles']:
			self.list.append(label('No games yet.', ['muted']))
		for p in data['profiles']:
			app = p['application']
			card = box(Gtk.Orientation.HORIZONTAL, 16, ['card'])
			titles = box(spacing=2, hexpand=True)
			titles.append(label(app.get('name') or 'Game', ['stage-title']))
			how = app.get('application_path') or ''
			steam = app.get('game', {}).get('steam', {}).get('id')
			how = ' · '.join(x for x in (how, f'Steam App {steam}' if steam else '') if x)
			running = p['id'] == data.get('active')
			titles.append(label(('Running now · ' if running else '') + how, ['muted', 'small']))
			card.append(titles)
			card.append(button_widget('Use current settings', ['ghost'], lambda i=p['id']: self._update(i)))
			card.append(button_widget('Delete', ['ghost'], lambda i=p['id']: self._delete(i)))
			self.list.append(card)
		self.active = data.get('active')

	def _add(self):
		name, exe, steam = self.name.get_text().strip(), self.exe.get_text().strip(), self.steam.get_text().strip()
		if not name or not (exe or steam.isdigit()):
			self.win.toast('A name, and an executable or a Steam App ID (a number)')
			return
		data = profiles.load()
		data['profiles'].append(profiles.new_profile(name, exe, steam))
		profiles.save(data)
		for e in (self.name, self.exe, self.steam):
			e.set_text('')
		self.refresh()

	def _update(self, pid):
		data = profiles.load()
		for p in data['profiles']:
			if p['id'] == pid:
				p['settings'] = profiles.snapshot()
		profiles.save(data)
		self.win.toast('Saved the current settings to the game')

	def _delete(self, pid):
		data = profiles.load()
		data['profiles'] = [p for p in data['profiles'] if p['id'] != pid]
		profiles.save(data)
		self.refresh()

	def _poll(self):
		if (store.read_status() or {}).get('game') != self.active:
			self.refresh()
		return True
