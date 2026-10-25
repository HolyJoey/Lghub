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
	effects = _effects(per_key, model)
	chosen = _chosen(effects, settings)
	effect = Gtk.DropDown.new_from_strings([name for _k, _f, name in effects])
	effect.set_selected(chosen)
	card.append(_row('Effect', effect))

	color = _color_button(settings.get('color', [0, 140, 255]))
	audio_rows, audio_values, audio_widgets = _audio_controls(settings)
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
	wave1 = _color_button(settings.get('color', list(lightsync.signature_defaults(model, 'smooth_wave')[0])))
	wave2 = _color_button(settings.get('color2', list(lightsync.signature_defaults(model, 'smooth_wave')[1])))
	star1 = _color_button(settings.get('color', list(lightsync.signature_defaults(model, 'smooth_star')[0])))
	star2 = _color_button(settings.get('color2', list(lightsync.signature_defaults(model, 'smooth_star')[1])))
	pulse1 = _color_button(settings.get('color', list(lightsync.signature_defaults(model, 'pulsar_point')[0])))
	pulse2 = _color_button(settings.get('color2', list(lightsync.signature_defaults(model, 'pulsar_point')[1])))
	remind = _color_button(settings.get('color', list(lightsync.signature_defaults(model, 'remind_me_of')[0])))
	g3a = _color_button(settings.get('color', list(lightsync.signature_defaults(model, 'g_3_series')[0])))
	g3b = _color_button(settings.get('color2', list(lightsync.signature_defaults(model, 'g_3_series')[1])))
	neon_c = _color_button(settings.get('color', list(lightsync.signature_defaults(model, 'neon')[0])))
	space_c = _color_button(settings.get('color', list(lightsync.signature_defaults(model, 'outer_space')[0])))
	tide1 = _color_button(settings.get('color', list(lightsync.signature_defaults(model, 'g_tide')[0])))
	tide2 = _color_button(settings.get('color2', list(lightsync.signature_defaults(model, 'g_tide')[1])))
	regions = Gtk.Button(label='Edit regions')

	def edit_regions(_b):
		import region_editor
		region_editor.RegionEditor(regions.get_root(), model, per_key).present()

	regions.connect('clicked', edit_regions)
	rows = {'audio': [('Colour', color)] + audio_rows,
	        'screen': [('Colour boost', boost), ('Smoothing', smoothing), ('Screen regions', regions)],
	        'starlight': [('Star colour', star), ('Sky colour', sky), ('Stars', count), ('Speed', speed)],
	        'cycle': [('Speed', cycle_speed)],
	        'echo': [('Echo colour', echo), ('Rest colour', rest), ('Fade', echo_speed)],
	        'smooth_wave': [('Colour', wave1), (SECOND_COLOUR, wave2)],
	        'smooth_star': [('Start colour', star1), ('Colour', star2)],
	        'pulsar_point': [('Logo colour', pulse1), ('Pulse colour', pulse2)],
	        'remind_me_of': [('Colour', remind)],
	        'g_3_series': [('Colour', g3a), ('Centre colour', g3b)],
	        'neon': [('Colour', neon_c)],
	        'outer_space': [('Colour', space_c)],
	        'g_tide': [('Colour', tide1), (SECOND_COLOUR, tide2)]}
	widgets = _add_rows(card, rows)

	def show():
		kind = effects[effect.get_selected()][0]
		_show(widgets, kind)
		return kind

	def changed(*_):
		kind = show()
		data = lightsync.load()
		values = {'audio': lambda: {'color': _rgb(color), **audio_values()},
		          'screen': lambda: {'color_boost': round(boost.get_value()), 'smoothing': smoothing.get_active(),
		                             'regions': data.get(model, {}).get('regions', {})},
		          'starlight': lambda: {'star': _rgb(star), 'sky': _rgb(sky), 'count': round(count.get_value()),
		                                'speed': round(speed.get_value())},
		          'cycle': lambda: {'speed': round(cycle_speed.get_value())},
		          'echo': lambda: {'echo': _rgb(echo), 'rest': _rgb(rest), 'speed': round(echo_speed.get_value())},
		          'smooth_wave': lambda: {'color': _rgb(wave1), 'color2': _rgb(wave2)},
		          'smooth_star': lambda: {'color': _rgb(star1), 'color2': _rgb(star2)},
		          'pulsar_point': lambda: {'color': _rgb(pulse1), 'color2': _rgb(pulse2)},
		          'remind_me_of': lambda: {'color': _rgb(remind)},
		          'g_3_series': lambda: {'color': _rgb(g3a), 'color2': _rgb(g3b)},
		          'neon': lambda: {'color': _rgb(neon_c)},
		          'outer_space': lambda: {'color': _rgb(space_c)},
		          'g_tide': lambda: {'color': _rgb(tide1), 'color2': _rgb(tide2)},
		          'keyframe': lambda: {'file': effects[effect.get_selected()][1]},
		          'custom': lambda: {'custom': effects[effect.get_selected()][1]}}
		if kind:
			data[model] = {'effect': 'keyframe' if kind == 'custom' else kind, **values[kind]()}
		else:
			data.pop(model, None)
			restore()                        # the device's own lighting back on
		lightsync.save(data)

	show()
	effect.connect('notify::selected', changed)
	for w in audio_widgets:
		w.connect(_signal(w), changed)
	for w in (color, star, sky, echo, rest):
		w.connect('notify::rgba', changed)
	for w in (boost, count, speed, cycle_speed, echo_speed):
		w.connect('value-changed', changed)
	smoothing.connect('notify::active', changed)
	return card


def _add_rows(card, rows):
	"""{effect: [row widgets]} after adding every effect's setting rows to the card."""
	widgets = {}
	for kind, items in rows.items():
		for text, w in items:
			r = _row(text, w)
			card.append(r)
			widgets.setdefault(kind, []).append(r)
	return widgets


def _show(widgets, kind):
	for k, rows in widgets.items():
		for r in rows:
			r.set_visible(k == kind)


REGION_EDITS = ('regions', 'region_names', 'assign')      # the region editor's saved changes

SIGNALS = ((Gtk.ColorDialogButton, 'notify::rgba'), (Gtk.Scale, 'value-changed'), (Gtk.DropDown, 'notify::selected'))


def _signal(widget):
	"""The signal a setting widget sends when it changes."""
	return next((sig for kind, sig in SIGNALS if isinstance(widget, kind)), 'notify::active')


MODES = (('fixed', 'Fixed'), ('reactive', 'Reactive (to the second colour when loud)'),
         ('gradient', 'Gradient (bottom to top)'))


def _audio_controls(settings):
	"""G HUB's audio visualizer settings: colour mode, second and background colour, boost, max
	amplitude (adaptive or set), noise thresholds, smooth animation (ranges as G HUB's sliders)."""
	mode = Gtk.DropDown.new_from_strings([text for _k, text in MODES])
	mode.set_selected(next((i for i, (k, _t) in enumerate(MODES) if k == settings.get('mode')), 0))
	high = _color_button(settings.get('color_high', [255, 40, 40]))
	background = _color_button(settings.get('background', [0, 0, 0]))
	boost = _slider(0, 100, settings.get('boost', 0), ' %')
	adaptive = Gtk.Switch(active=settings.get('adaptive', True), valign=Gtk.Align.CENTER)
	top = _slider(0, 100, settings.get('max_amplitude', 100), ' %')
	bass = _slider(0, 100, settings.get('bass_noise', 0), ' %')
	mid = _slider(0, 100, settings.get('mid_high_noise', 0), ' %')
	smooth = Gtk.Switch(active=settings.get('smooth', False), valign=Gtk.Align.CENTER)
	clip = Gtk.Switch(active=settings.get('clip', False), valign=Gtk.Align.CENTER)
	clip_color = _color_button(settings.get('clip_color', [255, 0, 0]))
	clip_at = _slider(0, 100, settings.get('clip_threshold', 80), ' %')
	rows = [('Colour mode', mode), (SECOND_COLOUR, high), ('Background', background), ('Audio boost', boost),
	        ('Adaptive max amplitude', adaptive), ('Max amplitude', top), ('Bass noise threshold', bass),
	        ('Mid / high noise threshold', mid), ('Smooth animation', smooth), ('Clip zone', clip),
	        ('Clip zone colour', clip_color), ('Clip zone threshold', clip_at)]

	def values():
		return {'mode': MODES[mode.get_selected()][0], 'color_high': _rgb(high), 'background': _rgb(background),
		        'boost': round(boost.get_value()), 'adaptive': adaptive.get_active(),
		        'max_amplitude': round(top.get_value()), 'bass_noise': round(bass.get_value()),
		        'mid_high_noise': round(mid.get_value()), 'smooth': smooth.get_active(), 'clip': clip.get_active(),
		        'clip_color': _rgb(clip_color), 'clip_threshold': round(clip_at.get_value())}

	return rows, values, [w for _t, w in rows]


def _chosen(effects, settings):
	"""The list position of the effect in settings (0 = off)."""
	for i, (kind, file, _name) in enumerate(effects):
		if kind == 'custom' and file == settings.get('custom'):
			return i
		if kind == settings.get('effect') and file == settings.get('file') and not settings.get('custom'):
			return i
	return 0


def _intro(per_key):
	if per_key:
		return ('Effects the background service plays on the keys: G HUB’s own animations, its signature '
		        'effects, '
		        'starlight, colour cycle, echo press, the audio visualizer (bass left, treble right) and the screen sampler (grim, or '
		        'the desktop’s screen sharing, which asks once). Your colours come back when it is off.')
	return ('Effects the background service plays on the lighting zones: starlight, colour cycle, echo press '
	        '(clicks), the audio visualizer and the screen sampler (grim, or the desktop’s screen sharing, which asks '
	        'once). When it is off, a mouse with onboard memory gets its profile’s lighting back; on others set the '
	        'zones again.')


SECOND_COLOUR = 'Second colour'
SIGNATURE_NAMES = {'SIGNATURE_FRAME_ACTIVE': 'Signature (active)', 'SIGNATURE_FRAME_INACTIVE': 'Signature (idle)'}


def _effects(per_key, model=None):
	import softlight
	effects = [(None, None, 'Off'), ('audio', None, 'Audio visualizer'), ('screen', None, 'Screen sampler'),
	           ('starlight', None, 'Starlight'), ('cycle', None, 'Colour cycle'), ('echo', None, 'Echo press')]
	if per_key:
		own = [('device', name, SIGNATURE_NAMES.get(name, name.replace('_', ' ').capitalize()))
		       for name, _e in softlight.device_effects(model)] if model else []
		signature = [('smooth_star', None, 'Smooth Star'), ('smooth_wave', None, 'Smooth Wave'),
		             ('pulsar_point', None, 'Pulsar Point'), ('remind_me_of', None, 'Remind Me Of'),
		             ('g_3_series', None, 'G 3 Series'), ('neon', None, 'Neon'),
		             ('outer_space', None, 'Outer Space'), ('g_tide', None, 'G Tide')]
		offered = lightsync.signature_effects(model) if model else None     # G HUB's list for this model
		if offered is not None:
			signature = [e for e in signature if e[0] in offered]
		return effects + signature + own + _keyframe_effects() + [
			('custom', file, name) for name, file in softlight.custom_effects()]
	return effects                                     # G HUB: no keyframe animations on zones


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
