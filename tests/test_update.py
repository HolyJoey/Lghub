"""Updates from GitHub releases: version checks, signature and hash, safe unpacking, and the
install with its backup (a throwaway signing key and release, no network)."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import update  # noqa: E402


def make_tarball(files, prefix='lghub-9.9.9/'):
	buf = io.BytesIO()
	with tarfile.open(fileobj=buf, mode='w:gz') as tar:
		for name, text, mode in files:
			data = text.encode()
			info = tarfile.TarInfo(prefix + name if not name.startswith(('/', '..')) else name)
			info.size, info.mode = len(data), mode
			tar.addfile(info, io.BytesIO(data))
	return buf.getvalue()


class UpdateTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.keys = tempfile.TemporaryDirectory()
		cls.key = os.path.join(cls.keys.name, 'key')
		subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', cls.key], check=True)

	@classmethod
	def tearDownClass(cls):
		cls.keys.cleanup()

	def sign(self, data):
		r = subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', self.key, '-n', update.NAMESPACE], input=data,
		                   capture_output=True, check=True)
		return r.stdout

	def test_versions(self):
		self.assertEqual(update.parse('v1.2.3'), (1, 2, 3, 0))
		self.assertEqual(update.parse('1.2.3.4'), (1, 2, 3, 4))
		self.assertIsNone(update.parse('1.2'))
		self.assertIsNone(update.parse('1.2.3.4.5'))
		self.assertTrue(update.newer('0.10.0', '0.9.9'))
		self.assertTrue(update.newer('0.9.8.1', '0.9.8'))
		self.assertTrue(update.newer('0.9.9', '0.9.8.3'))
		self.assertFalse(update.newer('0.9.8.0', '0.9.8'))
		self.assertFalse(update.newer('0.9.0', '0.9.0'))
		self.assertFalse(update.newer('garbage', '0.9.0'))

	def test_latest_ignores_older_and_prereleases(self):
		release = {'tag_name': 'v9.9.9', 'body': 'notes', 'prerelease': False,
		           'assets': [{'name': 'lghub-9.9.9.tar.gz', 'browser_download_url': 'https://x/t'}]}
		with mock.patch.object(update, '_get', return_value=json.dumps(release).encode()):
			info = update.latest()
		self.assertEqual((info['version'], info['notes'], info['assets']['lghub-9.9.9.tar.gz']),
		                 ('9.9.9', 'notes', 'https://x/t'))
		for changed in ({'prerelease': True}, {'tag_name': 'v0.0.1'}):
			with mock.patch.object(update, '_get', return_value=json.dumps({**release, **changed}).encode()):
				self.assertIsNone(update.latest())

	def test_check_remembers_and_pending(self):
		with tempfile.TemporaryDirectory() as tmp:
			path = os.path.join(tmp, 'update.json')
			with mock.patch.object(update, 'UPDATE_FILE', path), \
					mock.patch.object(update, 'latest', return_value={'version': '9.9.9', 'notes': '', 'assets': {}}):
				update.check()
				self.assertEqual(update.pending()['version'], '9.9.9')
			with mock.patch.object(update, 'UPDATE_FILE', path), mock.patch.object(update, 'latest', side_effect=OSError):
				self.assertIsNone(update.check())                         # offline: keeps the last answer
				self.assertEqual(update.pending()['version'], '9.9.9')

	def test_verify(self):
		data = b'release'
		sha = hashlib.sha256(data).hexdigest() + '  lghub.tar.gz\n'
		good, wrong = self.sign(data), self.sign(b'something else')
		key = self.key + '.pub'
		update.verify(data, sha, good, key)
		with self.assertRaises(ValueError):
			update.verify(b'other', sha, good, key)          # checksum
		with self.assertRaises(ValueError):
			update.verify(data, sha, wrong, key)             # signature

	def test_unpack_is_safe(self):
		with tempfile.TemporaryDirectory() as tmp:
			src = update.unpack(make_tarball([('install.sh', 'exit 0', 0o755)]), tmp)
			self.assertTrue(os.path.isfile(os.path.join(src, 'install.sh')))
		evil = make_tarball([('install.sh', 'exit 0', 0o755), ('../escape', 'x', 0o644)])
		with tempfile.TemporaryDirectory() as tmp, self.assertRaises(tarfile.TarError):
			update.unpack(evil, tmp)

	def install_with(self, script):
		"""Runs update.install on a release whose install.sh is script; returns (result or error, app dir files)."""
		tarball = make_tarball([('install.sh', script, 0o755), ('app.py', 'new', 0o644)])
		name = 'lghub-9.9.9.tar.gz'
		files = {name: tarball, name + '.sha256': hashlib.sha256(tarball).hexdigest().encode(),
		         name + '.sig': self.sign(tarball)}
		info = {'version': '9.9.9', 'notes': '', 'assets': {n: n for n in files}}
		with tempfile.TemporaryDirectory() as tmp:
			app = os.path.join(tmp, 'lghub')
			os.makedirs(app)
			with open(os.path.join(app, 'app.py'), 'w') as f:
				f.write('old')
			with mock.patch.object(update, '_get', side_effect=lambda url, _limit, *_a: files[url]), \
					mock.patch.object(update, 'KEY_FILE', self.key + '.pub'), \
					mock.patch.object(update, 'APP_DIR', app), mock.patch.object(update, 'BACKUP_DIR', app + '-previous'), \
					mock.patch.dict(os.environ, {'LGHUB_TARGET': app, 'HOME': tmp}):
				try:
					result = update.install(info)
				except (update.NeedsRoot, RuntimeError, ValueError) as e:
					result = e
				with open(os.path.join(app, 'app.py')) as f:
					return result, f.read()

	def test_install_success(self):
		result, app = self.install_with('cp app.py "$LGHUB_TARGET/app.py"; echo installed')
		self.assertIn('installed', result)
		self.assertEqual(app, 'new')

	def test_install_failure_puts_the_backup_back(self):
		with mock.patch('subprocess.run', wraps=subprocess.run) as run:
			result, app = self.install_with('cp app.py "$LGHUB_TARGET/app.py"; echo broken >&2; exit 1')
		self.assertIsInstance(result, RuntimeError)
		self.assertIn('broken', str(result))
		self.assertEqual(app, 'old')                                       # restored
		self.assertIn(['systemctl', '--user', 'restart', 'lghub.service'], [c.args[0] for c in run.call_args_list])

	def test_install_needing_root_keeps_the_release(self):
		with mock.patch('subprocess.run', wraps=subprocess.run):
			result, app = self.install_with('echo "Missing on this system"; exit 3')
		self.assertIsInstance(result, update.NeedsRoot)
		self.assertIn('Missing', result.output)
		self.assertTrue(result.folder.endswith(os.path.join('update', '9.9.9')))
		self.assertEqual(app, 'old')

	def test_can_install(self):
		with tempfile.TemporaryDirectory() as tmp, mock.patch.object(update, 'APP_DIR', tmp):
			self.assertFalse(update.can_install())                      # a checkout: no marker
			with open(os.path.join(tmp, 'install-source'), 'w') as f:
				f.write('script\n')
			self.assertTrue(update.can_install())


if __name__ == '__main__':
	unittest.main()
