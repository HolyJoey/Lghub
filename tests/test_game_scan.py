import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import game_scan  # noqa: E402


def write(path, text):
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, 'w') as f:
		f.write(text)


class GameScanTest(unittest.TestCase):
	def test_two_libraries_without_tools(self):
		with tempfile.TemporaryDirectory() as d:
			root, other = os.path.join(d, 'steam'), os.path.join(d, 'games')
			write(os.path.join(root, 'steamapps', 'libraryfolders.vdf'),
			      f'"libraryfolders"\n{{\n "0"\n {{\n  "path" "{root}"\n }}\n "1"\n {{\n  "path" "{other}"\n }}\n}}\n')
			write(os.path.join(root, 'steamapps', 'appmanifest_730.acf'),
			      '"AppState"\n{\n "appid" "730"\n "name" "Counter-Strike 2"\n}\n')
			write(os.path.join(root, 'steamapps', 'appmanifest_1493710.acf'),
			      '"AppState"\n{\n "appid" "1493710"\n "name" "Proton Experimental"\n}\n')
			write(os.path.join(other, 'steamapps', 'appmanifest_1245620.acf'),
			      '"AppState"\n{\n "appid" "1245620"\n "name" "ELDEN RING"\n}\n')
			self.assertEqual(game_scan.steam_games((root,)), [('730', 'Counter-Strike 2'), ('1245620', 'ELDEN RING')])


	def test_epic_and_lutris(self):
		import sqlite3
		with tempfile.TemporaryDirectory() as d:
			legendary = os.path.join(d, 'installed.json')
			write(legendary, '{"Fortnite": {"title": "Fortnite", "executable": "FortniteGame/Binaries/Win64/FortniteLauncher.exe"}}')
			self.assertEqual(game_scan.epic_games((legendary,)), [('Fortnite', 'FortniteLauncher.exe')])
			db = os.path.join(d, 'pga.db')
			conn = sqlite3.connect(db)
			conn.execute('CREATE TABLE games (name TEXT, configpath TEXT, installed INTEGER)')
			conn.executemany('INSERT INTO games VALUES (?, ?, ?)', [('Diablo II', 'diablo-ii-123', 1), ('Gone', 'gone-1', 0)])
			conn.commit()
			conn.close()
			write(os.path.join(d, 'games', 'diablo-ii-123.yml'), 'game:\n  exe: /home/x/Games/d2/Game.exe\n  prefix: /x\nsystem: {}\n')
			self.assertEqual(game_scan.lutris_games((db,), (os.path.join(d, 'games'),)), [('Diablo II', 'Game.exe')])


if __name__ == '__main__':
	unittest.main()
