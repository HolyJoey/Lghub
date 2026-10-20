"""Lghub's own settings, like G HUB's general settings page: desktop notifications, the tray icon
and the persistent profile (a game profile that stays on whatever runs)."""
from gi.repository import Gtk

import profiles
import store
from ui import box, button_widget, label, page_header


def _switch(key, default=True):
	sw = Gtk.Switch(active=store.load_config().get(key, default), valign=Gtk.Align.CENTER)

	def changed(w, _p):
		cfg = store.load_config()
		cfg[key] = w.get_active()
		store.save_config(cfg)

	sw.connect('notify::active', changed)
	return sw


def _row(text, widget, hint=None):
	r = box(Gtk.Orientation.HORIZONTAL, 16)
	titles = box(spacing=2, hexpand=True)
	titles.append(label(text, valign=Gtk.Align.CENTER))
	if hint:
		titles.append(label(hint, ['muted', 'small'], wrap=True))
	r.append(titles)
	r.append(widget)
	return r


class SettingsPage(Gtk.Box):
	def __init__(self, win):
		super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=20, css_classes=['page'])
		self.append(page_header('Settings', 'Lghub itself: notifications, the tray and profiles.',
		                        button_widget('Devices', ['ghost'], win.show_home)))
		notes = box(spacing=12, css=['card'])
		notes.append(label('Notifications', ['section-title']))
		notes.append(_row('Low battery', _switch('battery_warnings'), 'At 30 % and again at 15 %.'))
		notes.append(_row('DPI, profile and report rate changes', _switch('osd_notifications'),
		                  'When a mouse’s own buttons change them.'))
		notes.append(_row('Equalizer, surround and audio device changes', _switch('audio_notifications'),
		                  'When a button or macro changes them.'))
		notes.append(_row('Game profiles', _switch('profile_notifications'), 'When a game’s profile switches on or off.'))
		self.append(notes)

		tray = box(spacing=12, css=['card'])
		tray.append(label('Tray', ['section-title']))
		tray.append(_row('Show the tray icon', _switch('tray'), 'Devices, battery and quick switches. Takes effect '
		                 'when the background service restarts (or at the next login).'))
		self.append(tray)

		persist = box(spacing=12, css=['card'])
		persist.append(label('Persistent profile', ['section-title']))
		data = profiles.load()
		self.choices = [(None, 'None: switch with the games')] + [(p['id'], p['application'].get('name') or 'Game')
		                                                            for p in data['profiles']]
		dd = Gtk.DropDown.new_from_strings([name for _i, name in self.choices])
		dd.set_selected(next((n for n, (i, _name) in enumerate(self.choices) if i == data.get('persistent')), 0))
		dd.connect('notify::selected', self._persistent)
		persist.append(_row('Keep this profile on', dd, 'As G HUB’s persistent profile: it stays on whatever runs.'))
		self.append(persist)

	def _persistent(self, dd, _p):
		data = profiles.load()
		pid = self.choices[dd.get_selected()][0]
		if pid:
			data['persistent'] = pid
		else:
			data.pop('persistent', None)
		profiles.save(data)
