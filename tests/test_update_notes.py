"""Release notes in the update dialog: simple Markdown turned into paragraphs and bullets."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import gi  # noqa: E402

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
import update_ui  # noqa: E402


class NotesTest(unittest.TestCase):
	def test_blocks(self):
		text = '**New**\n- One thing that\n  wraps & goes on.\n- Two.\n\nLast line\nwrapped.\n'
		self.assertEqual(update_ui.notes_blocks(text), [
			('p', '<b>New</b>'), ('li', 'One thing that wraps &amp; goes on.'), ('li', 'Two.'),
			('gap', ''), ('p', 'Last line wrapped.')])


if __name__ == '__main__':
	unittest.main()
