"""Per-game profiles: recognising a running game and switching settings around it."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import profiles  # noqa: E402


class RunningTest(unittest.TestCase):
	def setUp(self):
		self.cs = profiles.new_profile('Counter-Strike 2', steam_id='730')
		self.cs['settings'] = {}
		self.proton = profiles.new_profile('Elden Ring', executable='C:\\Games\\ELDEN RING\\eldenring.exe')
		self.proton['settings'] = {}

	def test_steam_app_id(self):
		procs = ({'reaper', 'cs2'}, ['/home/u/.steam/ubuntu12_32/reaper steamlaunch appid=730 -- cs2'])
		self.assertIs(profiles.running([self.proton, self.cs], procs), self.cs)

	def test_proton_executable(self):
		procs = ({'eldenring.exe', 'wineserver'}, ['z:\\games\\elden ring\\eldenring.exe'])
		self.assertIs(profiles.running([self.cs, self.proton], procs), self.proton)

	def test_nothing_running(self):
		self.assertIsNone(profiles.running([self.cs, self.proton], ({'bash'}, ['bash'])))
		self.assertIsNone(profiles.running([self.cs], ({'bash'}, ['reaper steamlaunch appid=7300'])))


class SwitcherTest(unittest.TestCase):
	def test_switch_and_back(self):
		with tempfile.TemporaryDirectory() as d:
			state = {'eq': 'desktop'}

			def snapshot():
				return {'equalizer': state['eq']}

			def restore(settings):
				state['eq'] = settings.get('equalizer')

			with mock.patch.object(profiles, 'FILE', os.path.join(d, 'g.json')), \
					mock.patch.object(profiles, 'snapshot', snapshot), mock.patch.object(profiles, 'restore', restore), \
					mock.patch.object(profiles, '_notify') as notify:
				game = profiles.new_profile('Game', executable='game')
				game['settings'] = {'equalizer': 'fps'}
				profiles.save({'profiles': [game]})
				sw = profiles.Switcher()
				with mock.patch.object(profiles, '_processes', return_value=({'game'}, ['game'])):
					self.assertEqual(sw.check(0), game['id'])
				self.assertEqual(state['eq'], 'fps')
				state['eq'] = 'fps tweaked'                     # changed while the game runs
				with mock.patch.object(profiles, '_processes', return_value=({'bash'}, ['bash'])):
					self.assertIsNone(sw.check(10))
				self.assertEqual(state['eq'], 'desktop')
				self.assertEqual(profiles.load()['profiles'][0]['settings'], {'equalizer': 'fps tweaked'})
				self.assertEqual([c.args[0] for c in notify.call_args_list], ['Game profile on', 'Desktop profile on'])


	def test_persistent_profile(self):
		data = {'profiles': [{'id': 'a'}, {'id': 'b'}], 'persistent': 'b'}
		self.assertEqual(profiles.persistent(data), {'id': 'b'})
		self.assertIsNone(profiles.persistent({'profiles': [{'id': 'a'}]}))


if __name__ == '__main__':
	unittest.main()
