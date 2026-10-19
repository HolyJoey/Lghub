"""The LIGHTSYNC card (G HUB's software effects) for per-key keyboards and zonal devices; the
background service plays the chosen effect (lightsync.py)."""
import json
import os
import threading

from gi.repository import Gdk, Gtk

from ui import box, label


def card(model, restore, per_key=True):
	"""G HUB's software effects for one device model (lightsync.py); restore() puts the device's own
	colours back when the effect is switched off. Zonal devices get the effects G HUB offers them."""
	import lightsync
	import softlight
	settings = lightsync.load().get(model, {})
	card = box(spacing=10, css=['card'])
	card.append(label('LIGHTSYNC', ['section-title']))
	card.append(label(_intro(per_key), ['muted', 'small'], wrap=True))
	effects = _effects(per_key)
	chosen = next((i for i, (k, f, _n) in enumerate(effects)
	               if k == settings.get('effect') and f == settings.get('file')), 0)
	effect = Gtk.DropDown.new_from_strings([name for _k, _f, name in effects])
	effect.set_selected(chosen)
	card.append(_row('Effect', effect))

	color = _color_button(settings.get('color', [0, 140, 255]))
	boost = _slider(0, 100, settings.get('color_boost', 0), ' %')          # G HUB's 0-100 %
	smoothing = Gtk.Switch(active=settings.get('smoothing', False), valign=Gtk.Align.CENTER)
	star = _color_button(settings.get('star', [255, 255, 255]))
	sky = _color_button(settings.get('sky', [0, 0, 40]))
	count = _slider(*softlight.STAR_COUNT, settings.get('count', 50), '')
	speed = _slider(*softlight.STAR_SPEED, settings.get('speed', 2000), ' ms')
	cycle_speed = _slider(*softlight.CYCLE_SPEED, settings.get('speed', 5000), ' ms')
	echo = _color_button(settings.get('echo', [255, 255, 255]))
	rest = _color_button(settings.get('rest', [0, 0, 0]))
	echo_speed = _slider(*softlight.STAR_SPEED, settings.get('speed', 1000), ' ms')
	regions = Gtk.Button(label='Edit regions')

	def edit_regions(_b):
		import region_editor
		region_editor.RegionEditor(regions.get_root(), model, per_key).present()

	regions.connect('clicked', edit_regions)
	rows = {'audio': [('Colour', color)],
	        'screen': [('Colour boost', boost), ('Smoothing', smoothing), ('Screen regions', regions)],
	        'starlight': [('Star colour', star), ('Sky colour', sky), ('Stars', count), ('Speed', speed)],
	        'cycle': [('Speed', cycle_speed)],
	        'echo': [('Echo colour', echo), ('Rest colour', rest), ('Fade', echo_speed)]}
	widgets = {}
	for kind, items in rows.items():
		for text, w in items:
			r = _row(text, w)
			card.append(r)
			widgets.setdefault(kind, []).append(r)

	def show():
		kind = effects[effect.get_selected()][0]
		for k, rs in widgets.items():
			for r in rs:
				r.set_visible(k == kind)
		return kind

	def changed(*_):
		kind = show()
		data = lightsync.load()
		values = {'audio': lambda: {'color': _rgb(color)},
		          'screen': lambda: {'color_boost': round(boost.get_value()), 'smoothing': smoothing.get_active(),
		                             'regions': data.get(model, {}).get('regions', {})},
		          'starlight': lambda: {'star': _rgb(star), 'sky': _rgb(sky), 'count': round(count.get_value()),
		                                'speed': round(speed.get_value())},
		          'cycle': lambda: {'speed': round(cycle_speed.get_value())},
		          'echo': lambda: {'echo': _rgb(echo), 'rest': _rgb(rest), 'speed': round(echo_speed.get_value())},
		          'keyframe': lambda: {'file': effects[effect.get_selected()][1]}}
		if kind:
			data[model] = {'effect': kind, **values[kind]()}
		else:
			data.pop(model, None)
			restore()                        # the device's own lighting back on
		lightsync.save(data)

	show()
	effect.connect('notify::selected', changed)
	for w in (color, star, sky, echo, rest):
		w.connect('notify::rgba', changed)
	for w in (boost, count, speed, cycle_speed, echo_speed):
		w.connect('value-changed', changed)
	smoothing.connect('notify::active', changed)
	return card


def _intro(per_key):
	if per_key:
		return ('Effects the background service plays on the keys: G HUB’s own animations, starlight, colour '
		        'cycle, echo press, the audio visualizer (bass left, treble right) and the screen sampler (needs '
		        'grim: Hyprland, Sway). Your colours come back when it is off.')
	return ('Effects the background service plays on the lighting zones: starlight, colour cycle, the audio '
	        'visualizer and the screen sampler (needs grim: Hyprland, Sway). When it is off, a mouse with '
	        'onboard memory gets its profile’s lighting back; on others set the zones again.')


def _effects(per_key):
	effects = [(None, None, 'Off'), ('audio', None, 'Audio visualizer'), ('screen', None, 'Screen sampler'),
	           ('starlight', None, 'Starlight'), ('cycle', None, 'Colour cycle'), ('echo', None, 'Echo press')]
	if per_key:
		return effects + _keyframe_effects()
	return [e for e in effects if e[0] != 'echo']      # G HUB: no echo press or animations on zones


def _color_button(rgb):
	b = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
	rgba = Gdk.RGBA()
	rgba.red, rgba.green, rgba.blue = (c / 255 for c in rgb)
	rgba.alpha = 1.0
	b.set_rgba(rgba)
	return b

def _rgb(button):
	c = button.get_rgba()
	return [round(v * 255) for v in (c.red, c.green, c.blue)]

def _slider(lo, hi, value, unit):
	sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
	sc.set_value(value)
	sc.set_draw_value(True)
	sc.set_size_request(280, -1)
	sc.set_format_value_func(lambda _s, v: f'{v:.0f}{unit}')
	return sc


def _keyframe_effects():
	"""G HUB's animations for per-key keyboards, from its prefab list (fetched in the background the
	first time; there the next time the page opens)."""
	import softlight
	cached = os.path.join(softlight.CACHE, os.path.basename(softlight.PREFABS))
	try:
		with open(cached) as f:
			return [('keyframe', file, name) for name, file in softlight.keyboard_effects(json.load(f))]
	except (OSError, ValueError):
		threading.Thread(target=softlight.load_prefabs, daemon=True).start()
		return []


def _row(text, widget):
	r = box(Gtk.Orientation.HORIZONTAL, 16)
	r.append(label(text, hexpand=True, valign=Gtk.Align.CENTER))
	r.append(widget)
	return r
