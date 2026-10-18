"""Headset mixer parsing, equalizer config and webcam restore order."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import eq  # noqa: E402
import surround  # noqa: E402
import headset  # noqa: E402
import v4l2  # noqa: E402
import webcam  # noqa: E402

AMIXER = """Simple mixer control 'PCM',0
  Capabilities: pvolume pswitch pswitch-joined
  Playback channels: Front Left - Front Right
  Limits: Playback 0 - 100
  Mono:
  Front Left: Playback 50 [50%] [-20.00dB] [on]
  Front Right: Playback 50 [50%] [-20.00dB] [on]
Simple mixer control 'Mic',0
  Capabilities: cvolume cvolume-joined cswitch cswitch-joined
  Capture channels: Mono
  Limits: Capture 0 - 16
  Mono: Capture 12 [75%] [6.00dB] [on]
Simple mixer control 'Sidetone',0
  Capabilities: pvolume pvolume-joined pswitch pswitch-joined
  Playback channels: Mono
  Limits: Playback 0 - 32
  Mono: Playback 8 [25%] [-24.00dB] [off]
"""


class MixerTest(unittest.TestCase):
	def test_parse(self):
		pcm, mic, side = headset.parse_scontents(AMIXER)
		self.assertEqual((pcm.percent, pcm.on, pcm.capture, pcm.is_sidetone), (50, True, False, False))
		self.assertEqual((mic.percent, mic.capture, mic.has_volume, mic.has_switch), (75, True, True, True))
		self.assertEqual((side.percent, side.on, side.is_sidetone), (25, False, True))
		self.assertEqual(side.id, "'Sidetone',0")


class EqualizerTest(unittest.TestCase):
	def test_config(self):
		text = eq.config_text('alsa_output.usb-PRO_X', 'PRO X (Equalizer)', [1.5] * len(eq.BANDS))
		self.assertIn('label = bq_lowshelf', text)
		self.assertIn('label = bq_highshelf', text)
		self.assertEqual(text.count('label = bq_peaking'), len(eq.BANDS) - 2)
		self.assertIn('"Gain" = 1.50', text)
		self.assertIn('target.object = "alsa_output.usb-PRO_X"', text)
		self.assertIn('input = "band10:In"', text)

	def test_ghub_presets(self):
		import json
		import tempfile
		data = {'presets': [
			{'name': 'EQUALIZER_FPS', 'attribute': 'EQUALIZER',
			 'equalizer': {'type': 'ADVANCED', 'advanced': [0, 0, -6, -5, -3, -2, -3, -3, -5, -6]}},
			{'name': 'EQUALIZER_SIMPLE_DEFAULT_HIDDEN', 'attribute': 'EQUALIZER',
			 'equalizer': {'type': 'SIMPLE', 'advanced': [0] * 10}},
			{'name': 'BLUE_VOICE_PRESET_X', 'attribute': 'BLUE_VOICE_SETTINGS'}]}
		with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
			json.dump(data, f)
		try:
			found = eq.load_presets(f.name)
		finally:
			os.remove(f.name)
		self.assertEqual(list(found), ['Flat', 'FPS'])
		self.assertEqual(found['FPS'][2], -6.0)

	def test_presets_fit(self):
		for gains in eq.PRESETS.values():
			self.assertEqual(len(gains), len(eq.BANDS))
			self.assertTrue(all(abs(g) <= eq.RANGE for g in gains))


class SurroundTest(unittest.TestCase):
	def test_tuning_follows_the_headset(self):
		def sink(name, desc):
			return {'name': name, 'description': desc}
		self.assertEqual(surround.tuning(sink('alsa_output.usb-Logitech_PRO_X_000000-00.analog-stereo', 'PRO X')),
		                 'PRO_X')
		self.assertEqual(surround.tuning(sink('alsa_output.usb-Logitech_PRO_X_Wireless-00', 'PRO X Wireless')),
		                 'PRO_X_WIRELESS')
		self.assertEqual(surround.tuning(sink('alsa_output.usb-Logitech_G733-00', 'G733 Gaming Headset')), 'G733')

	def test_params(self):
		settings = surround.default_settings()
		settings['gains']['LFE'] = 0.5
		text = surround.params_text(settings)
		self.assertIn('gain_LFE 0.500', text)
		self.assertIn('room 1', text)          # G HUB's default, HX2E_GAMING
		settings['room'] = 'entertainment'
		self.assertIn('room 0', surround.params_text(settings))
		self.assertIn('gain_FL 1.100', text)
		self.assertNotIn('eq ', text)
		with_eq = surround.params_text(settings, {'enabled': True, 'gains': [3.0] * 10})
		self.assertIn('eq 1', with_eq)
		self.assertIn('eq_10 3.00', with_eq)


class FakeCamera:
	"""Auto exposure on makes exposure time inactive, like a UVC camera."""

	def __init__(self):
		self.values = {1: 3, 2: 100}
		self.log = []

	def controls(self):
		auto = v4l2.Control(1, v4l2.T_MENU, 'Auto Exposure', 0, 3, 1, 3, 0)
		auto.value = self.values[1]
		flags = v4l2.FLAG_INACTIVE if self.values[1] == 3 else 0
		exposure = v4l2.Control(2, v4l2.T_INTEGER, 'Exposure Time, Absolute', 1, 1000, 1, 100, flags)
		exposure.value = self.values[2]
		return [exposure, auto]

	def set(self, cid, value):
		self.log.append(cid)
		self.values[cid] = value


class WebcamTest(unittest.TestCase):
	def test_auto_modes_first(self):
		cam = FakeCamera()
		webcam.apply(cam, {'auto_exposure': 1, 'exposure_time_absolute': 400})
		self.assertEqual(cam.log, [1, 2])
		self.assertEqual(cam.values, {1: 1, 2: 400})

	def test_inactive_left_alone(self):
		cam = FakeCamera()
		webcam.apply(cam, {'exposure_time_absolute': 400})
		self.assertEqual(cam.log, [])


if __name__ == '__main__':
	unittest.main()
