import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import lightsync  # noqa: E402
import screencast  # noqa: E402


class ScreencastTest(unittest.TestCase):
	def test_unpad_drops_row_padding(self):
		rows = b'abc' + b'\0' + b'def' + b'\0'
		self.assertEqual(screencast.unpad(rows, 1, 2, 4), b'abcdef')
		self.assertEqual(screencast.unpad(b'abcdef', 2, 1, 6), b'abcdef')

	def test_pipeline_reads_small_rgb(self):
		text = screencast.pipeline_text(7, 42)
		self.assertIn('pipewiresrc fd=7 path=42', text)
		self.assertIn(f'format=RGB,width={screencast.WIDTH},height={screencast.HEIGHT}', text)

	@staticmethod
	def _sampler():
		return lightsync.ScreenSampler.__new__(lightsync.ScreenSampler)

	def test_grim_first(self):
		s = self._sampler()
		with mock.patch('subprocess.run') as run, mock.patch.object(lightsync, 'parse_ppm', return_value=(1, 1, b'abc')):
			grab = s._grabber()
			self.assertEqual(grab(), (1, 1, b'abc'))
		self.assertIsNone(s.screen)
		run.assert_called()

	def test_portal_when_grim_missing(self):
		s = self._sampler()
		screen = mock.Mock()
		with mock.patch('subprocess.run', side_effect=OSError('no grim')), \
				mock.patch.object(screencast, 'Screen', return_value=screen):
			grab = s._grabber()
		self.assertIs(grab, screen.grab)

	def test_neither(self):
		s = self._sampler()
		with mock.patch('subprocess.run', side_effect=OSError('no grim')), \
				mock.patch.object(screencast, 'Screen', side_effect=screencast.PortalError('cancelled')):
			self.assertIsNone(s._grabber())


if __name__ == '__main__':
	unittest.main()
