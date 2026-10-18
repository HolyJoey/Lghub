"""The background engine, as a systemd user service."""
import subprocess

UNIT = 'lghub-bluevoice.service'


def _systemctl(*args):
	try:
		return subprocess.run(['systemctl', '--user', *args, UNIT], capture_output=True, text=True, timeout=10)
	except (OSError, subprocess.TimeoutExpired):
		return None


def is_active():
	r = _systemctl('is-active')
	return bool(r) and r.stdout.strip() == 'active'


def is_enabled():
	r = _systemctl('is-enabled')
	return bool(r) and r.stdout.strip() == 'enabled'


def installed():
	r = _systemctl('cat')
	return bool(r) and r.returncode == 0


def start():
	_systemctl('start')


def restart():
	_systemctl('restart')


def stop():
	_systemctl('stop')


def set_autostart(on):
	_systemctl('enable' if on else 'disable')
