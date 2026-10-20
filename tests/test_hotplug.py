import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import hotplug  # noqa: E402


class HotplugTest(unittest.TestCase):
	def test_changes(self):
		with tempfile.TemporaryDirectory() as d:
			w = hotplug.Watch(d)
			self.assertTrue(w.changed())          # the first look
			self.assertFalse(w.changed())
			os.mkdir(os.path.join(d, '3-2'))
			self.assertTrue(w.changed())
		self.assertTrue(w.changed())              # gone: empty now
		missing = hotplug.Watch('/nonexistent')
		self.assertTrue(missing.changed())          # no directory counts as empty
		self.assertFalse(missing.changed())


if __name__ == '__main__':
	unittest.main()
