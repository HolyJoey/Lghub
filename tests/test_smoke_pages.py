"""Every page of the real window, for every simulated device (smoke_pages.py), without a Python error.
Slow (about two minutes): runs only with LGHUB_SMOKE=1 and a display (GDK_BACKEND=broadway works)."""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import simulate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
IDS = (simulate.MICE + simulate.MICE_X + simulate.MICE_X_PLUS + simulate.LIGHTS + simulate.KEYBOARDS
       + simulate.ANALOG_KEYBOARDS + simulate.YETIS + simulate.YETI_2 + simulate.CENTURION_HEADSETS
       + simulate.RECEIVERS + ('0aaa',))


@unittest.skipUnless(os.environ.get('LGHUB_SMOKE') == '1' and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
                                                            or os.environ.get('GDK_BACKEND') == 'broadway'),
                     'set LGHUB_SMOKE=1 with a display')
class SmokePagesTest(unittest.TestCase):
	def test_every_page_opens(self):
		env = {**os.environ, 'LGHUB_PREVIEW': '0', 'LGHUB_FAKE_DEVICES': ','.join(dict.fromkeys(IDS)),
		       'SMOKE_STEP_MS': os.environ.get('SMOKE_STEP_MS', '800')}
		run = subprocess.run([sys.executable, os.path.join(HERE, 'smoke_pages.py')], env=env, capture_output=True,
		                     text=True, timeout=900, check=False)
		errors = [block for block in run.stderr.split('SMOKE-ERROR ')[1:]]
		self.assertEqual(run.returncode, 0, '\n'.join(errors)[:4000])
		self.assertGreater(run.stderr.count('SMOKE-PAGE'), 50)


if __name__ == '__main__':
	unittest.main()
