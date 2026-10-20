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


class SnapshotTest(unittest.TestCase):
	def test_snapshot_and_restore(self):
		saved = {}
		cfg = {'enabled': True, 'preset': 'Radio', 'params': {}, 'input': 'mic'}
		with mock.patch('store.load_config', return_value=dict(cfg)), \
				mock.patch('store.save_config', lambda c: saved.update(voice=c)), \
				mock.patch('eq.load', return_value={'enabled': True}), \
				mock.patch('eq.save', lambda s: saved.update(eq=s)), \
				mock.patch('surround.load', return_value={'enabled': False}), \
				mock.patch('surround.save', lambda s: saved.update(surround=s)):
			snap = profiles.snapshot()
			self.assertNotIn('input', snap['voice'])                  # the mic choice isn't per game
			profiles.restore({**snap, 'voice': {'preset': 'Studio'}})
		self.assertEqual(saved['voice']['preset'], 'Studio')
		self.assertEqual(saved['voice']['input'], 'mic')
		self.assertEqual((saved['eq'], saved['surround']), ({'enabled': True}, {'enabled': False}))

	def test_processes_reads_proc(self):
		with tempfile.TemporaryDirectory() as root:
			for pid, cmd in (('12', b'/usr/bin/Game.exe\0--appid=440\0'), ('13', None), ('self', b'x\0')):
				os.makedirs(os.path.join(root, pid))
				if cmd is not None:
					with open(os.path.join(root, pid, 'cmdline'), 'wb') as f:
						f.write(cmd)
			real_open, real_listdir = open, os.listdir
			with mock.patch('os.listdir', lambda p: real_listdir(root) if p == '/proc' else real_listdir(p)), \
					mock.patch('builtins.open', lambda p, *a, **k: real_open(p.replace('/proc', root, 1), *a, **k)):
				names, lines = profiles._processes()
		self.assertIn('game.exe', names)
		self.assertIn('--appid=440', lines[0])


if __name__ == '__main__':
	unittest.main()
