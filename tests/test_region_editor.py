import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import gi  # noqa: E402
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
import lightsync  # noqa: E402
import region_editor  # noqa: E402


class MoveTest(unittest.TestCase):
	def test_move_and_resize_stay_on_screen(self):
		r = [0.1, 0.5, 0.3, 0.8]
		self.assertEqual([round(v, 3) for v in region_editor.moved(r, 0.1, 0.0, False)], [0.2, 0.5, 0.4, 0.8])
		self.assertEqual([round(v, 3) for v in region_editor.moved(r, 1.0, 1.0, False)], [0.8, 0.7, 1.0, 1.0])
		self.assertEqual([round(v, 3) for v in region_editor.moved(r, -0.5, 0.0, True)], [0.1, 0.5, 0.13, 0.8])



class EditTest(unittest.TestCase):
	def test_new_region_is_ghub_centred_box(self):
		rid, (name, rect) = region_editor.new_region({'a': 1, 'b': 2})
		self.assertEqual(name, 'Sample 3')
		self.assertEqual([round(v, 3) for v in rect], [0.4, 0.4, 0.6, 0.6])
		self.assertEqual(len(rid), 36)

	def test_click_gives_key_then_takes_it_back(self):
		keys = region_editor.toggled({'k': 'a'}, 'k', 'b')
		self.assertEqual(keys['k'], 'b')
		self.assertEqual(region_editor.toggled(keys, 'k', 'b')['k'], lightsync.BACKGROUND)

	def test_delete_sends_keys_to_background(self):
		regions, keys = region_editor.deleted({'a': 1, 'b': 2}, {'k': 'a', 'j': 'b'}, 'a')
		self.assertEqual(list(regions), ['b'])
		self.assertEqual(keys, {'k': lightsync.BACKGROUND, 'j': 'b'})

	def test_only_changes_are_saved(self):
		self.assertEqual(region_editor.changes({'k': 'a', 'j': 'b'}, {'k': 'a', 'j': 'c'}), {'j': 'c'})

	def test_sampler_uses_edits(self):
		regions = {'a': (0, 0, 1, 1), 'b': (0, 0, 0.5, 0.5)}
		settings = {'regions': {'b': [0, 0, 0.5, 0.5], 'n': [0.4, 0.4, 0.6, 0.6]}, 'assign': {'j': 'n'}}
		r, keys = lightsync.edit_sampler(regions, {'k': 'a', 'j': 'b', 'm': 'b'}, settings)
		self.assertEqual(set(r), {'b', 'n'})
		self.assertEqual(keys, {'k': lightsync.BACKGROUND, 'j': 'n', 'm': 'b'})
		self.assertEqual(lightsync.edit_sampler(regions, {'k': 'a'}, {}), (regions, {'k': 'a'}))


if __name__ == '__main__':
	unittest.main()
