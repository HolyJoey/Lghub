"""Updates from Lghub's GitHub releases (ours; G HUB updates itself through its own pipeline).

A release v<version> carries lghub-<version>.tar.gz (git archive of the tag), its .sha256 and a
.sig: an SSH signature (ssh-keygen -Y sign, namespace "lghub-release") made with the key whose
public half is release-key.pub in the installed app. Checking asks GitHub's API for the latest
release, anonymously, at most once a day (the background service) or when asked (Settings);
nothing else is sent. Installing: download, check the hash and the signature against the key
already installed, unpack safely, back up the program files, run the new install.sh without a
terminal, and put the backup back if it fails. Run from the window, not the service: the
installer restarts the service.

config.json "check_updates": false turns the daily check off.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request

import store
from version import VERSION

REPO = 'HolyJoey/Lghub'
LATEST = f'https://api.github.com/repos/{REPO}/releases/latest'
NAMESPACE = 'lghub-release'
CHECK_EVERY = 24 * 3600.0
TIMEOUT = 20
MAX_DOWNLOAD = 64 << 20
APP_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(APP_DIR, 'release-key.pub')
BACKUP_DIR = APP_DIR + '-previous'
PROGRAM = ('*.py', 'bin', 'lghub-logo.svg', 'release-key.pub', 'install-source')
UPDATE_FILE = os.path.join(store.RUN_DIR, 'update.json')   # what the last check found
NEEDS_ROOT = 3          # install.sh's exit status when something needs root (LGHUB_UPDATE=1)


def parse(version):
	"""(major, minor, patch) of '1.2.3' / 'v1.2.3'; None for anything else."""
	m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', version.strip())
	return tuple(int(x) for x in m.groups()) if m else None


def newer(candidate, current=VERSION):
	a, b = parse(candidate), parse(current)
	return bool(a and b and a > b)


def can_install():
	"""Whether this install may update itself: installed by install.sh (not a git checkout or a
	distro package, which only get the notice)."""
	marker = os.path.join(APP_DIR, 'install-source')
	try:
		with open(marker) as f:
			return f.read().strip() == 'script'
	except OSError:
		return False


def _get(url, limit, accept='application/octet-stream'):
	req = urllib.request.Request(url, headers={'User-Agent': f'Lghub/{VERSION}', 'Accept': accept})
	with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 - fixed https host
		data = r.read(limit + 1)
	if len(data) > limit:
		raise OSError('download larger than expected')
	return data


def latest():
	"""The newest release, if newer than this one: {'version', 'notes', 'assets': {name: url}}; else None."""
	release = json.loads(_get(LATEST, 1 << 20, 'application/vnd.github+json'))
	version = release.get('tag_name', '')
	if release.get('draft') or release.get('prerelease') or not newer(version):
		return None
	assets = {a['name']: a['browser_download_url'] for a in release.get('assets', [])}
	return {'version': version.lstrip('v'), 'notes': release.get('body') or '', 'assets': assets}


def check(now=None):
	"""latest(), remembered in the runtime dir for the window and the tray; None on failure."""
	try:
		info = latest()
	except (OSError, ValueError, KeyError) as e:
		print(f'update: check failed: {e}', flush=True)
		return None
	store.write_json(UPDATE_FILE, {'checked': now or time.time(), 'update': info})
	return info


def pending():
	"""The update the last check found, or None."""
	data = store.read_json(UPDATE_FILE, {})
	info = data.get('update')
	return info if info and newer(info.get('version', '')) else None


class Checker:
	"""Used by the engine: checks once a day when "check_updates" is on (the default)."""

	def __init__(self):
		self.last = 0.0

	def due(self, now):
		return store.load_config().get('check_updates', True) and now - self.last >= CHECK_EVERY

	def check(self, now):
		"""Starts a check on its own thread (the network can be slow; the engine loop can't wait)."""
		import threading
		self.last = now
		threading.Thread(target=check, args=(time.time(),), daemon=True).start()


def verify(tarball, sha_text, signature, key_file=None):
	"""Raises ValueError unless tarball matches its SHA-256 and the release key signed it."""
	if hashlib.sha256(tarball).hexdigest() != sha_text.split()[0].lower():
		raise ValueError('the download does not match its checksum')
	with tempfile.TemporaryDirectory() as tmp:
		with open(key_file or KEY_FILE) as f:
			key = f.read().strip()
		signers = os.path.join(tmp, 'allowed_signers')
		with open(signers, 'w') as f:
			f.write(f'{NAMESPACE} namespaces="{NAMESPACE}" {key}\n')
		sig = os.path.join(tmp, 'release.sig')
		with open(sig, 'wb') as f:
			f.write(signature)
		r = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', signers, '-I', NAMESPACE, '-n', NAMESPACE, '-s', sig],
		                   input=tarball, capture_output=True, timeout=60)
	if r.returncode != 0:
		raise ValueError('the download is not signed by Lghub\'s release key')


def unpack(tarball, dest):
	"""Unpacks into dest (no absolute paths, links out or devices: tarfile's data filter); returns
	the folder that holds install.sh."""
	path = os.path.join(dest, 'release.tar.gz')
	with open(path, 'wb') as f:
		f.write(tarball)
	with tarfile.open(path) as tar:
		tar.extractall(dest, filter='data')
	os.unlink(path)
	found = [d for d in os.listdir(dest) if os.path.isfile(os.path.join(dest, d, 'install.sh'))]
	if len(found) != 1:
		raise ValueError('the release has no installer')
	return os.path.join(dest, found[0])


def _program_files(root):
	import glob
	for pattern in PROGRAM:
		yield from glob.glob(os.path.join(root, pattern))


def backup():
	"""Copies the program files (not the downloaded Logitech files or settings) aside."""
	shutil.rmtree(BACKUP_DIR, ignore_errors=True)
	os.makedirs(BACKUP_DIR)
	for path in _program_files(APP_DIR):
		target = os.path.join(BACKUP_DIR, os.path.basename(path))
		(shutil.copytree if os.path.isdir(path) else shutil.copy2)(path, target)


def restore():
	for path in _program_files(BACKUP_DIR):
		target = os.path.join(APP_DIR, os.path.basename(path))
		if os.path.isdir(path):
			shutil.rmtree(target, ignore_errors=True)
			shutil.copytree(path, target)
		else:
			shutil.copy2(path, target)
	subprocess.run(['systemctl', '--user', 'restart', 'lghub.service'], capture_output=True)


class NeedsRoot(Exception):
	"""The new version needs something only root can install; the installer's output says what.
	folder: the unpacked release, kept so its install.sh can be run in a terminal."""

	def __init__(self, output, folder):
		super().__init__(output)
		self.output, self.folder = output, folder


def install(info, progress=lambda _text: None):
	"""Downloads, checks and installs info's release; returns the installer's output. Raises
	ValueError / OSError (nothing changed) or NeedsRoot / RuntimeError (backup put back)."""
	name = f'lghub-{info["version"]}.tar.gz'
	assets = info['assets']
	if not all(n in assets for n in (name, name + '.sha256', name + '.sig')):
		raise ValueError('the release is missing its files')
	progress('Downloading')
	tarball = _get(assets[name], MAX_DOWNLOAD)
	sha = _get(assets[name + '.sha256'], 4096).decode()
	sig = _get(assets[name + '.sig'], 4096)
	progress('Checking')
	verify(tarball, sha, sig)
	with tempfile.TemporaryDirectory() as tmp:
		src = unpack(tarball, tmp)
		progress('Installing')
		backup()
		r = subprocess.run(['bash', os.path.join(src, 'install.sh')], cwd=src, capture_output=True, text=True,
		                   timeout=900, env={**os.environ, 'LGHUB_UPDATE': '1'}, stdin=subprocess.DEVNULL)
		output = r.stdout + r.stderr
		if r.returncode == NEEDS_ROOT:
			kept = os.path.join(os.path.expanduser('~/.cache/lghub/update'), info['version'])
			shutil.rmtree(kept, ignore_errors=True)
			shutil.copytree(src, kept)
	if r.returncode != 0:
		restore()
		if r.returncode == NEEDS_ROOT:
			raise NeedsRoot(output, kept)
		raise RuntimeError(output)
	return output
