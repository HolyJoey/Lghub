#!/usr/bin/env python3
"""Blue VO!CE engine: keeps the virtual microphone running.

Runs bluevoice-bridge (which runs Logitech's APO under Wine), keeps the PipeWire links
mic -> bluevoice_dsp -> "Blue VO!CE Microphone" in place, applies config.json changes live, and
publishes status.json for the app. Meant to run as a systemd user service.
"""
import os
import signal
import subprocess
import threading
import time

import presets
import pw
import store

POLL = 0.25          # config / status interval, seconds
LINK_EVERY = 2.0     # link check interval, seconds
MAX_BACKOFF = 30.0


def wine_path(path):
	"""Unix path -> the Z: drive path Windows code inside Wine understands."""
	return 'Z:' + os.path.abspath(path).replace('/', '\\')


class Engine:
	def __init__(self):
		self.stop = threading.Event()
		self.proc = None
		self.ready = False
		self.meter = (-120.0, -120.0)
		self.last_error = ''
		self.backoff = 2.0
		self.next_start = 0.0
		self.config = store.load_config()
		self.config_mtime = None
		self.params_text = None
		self.input = None
		self.defaulted = False
		self.last_link_check = 0.0

	# --- configuration -------------------------------------------------------------------

	def reload_config(self):
		try:
			mtime = os.stat(store.CONFIG_FILE).st_mtime
		except FileNotFoundError:
			mtime = None
		if mtime == self.config_mtime and self.params_text is not None:
			return
		old_input, old_latency = self.config.get('input'), self.config.get('max_latency_ms')
		self.config_mtime = mtime
		self.config = store.load_config()
		if self.config.get('input') != old_input:
			self.last_link_check = 0.0  # relink now
		if self.config.get('max_latency_ms') != old_latency and self.proc:
			self.stop_bridge()  # the bridge only takes its latency at start; check_bridge restarts it
			self.next_start = 0.0
		if not self.config.get('make_default'):
			self.defaulted = False
		params = {**presets.DEFAULTS, **self.config['params']}
		params['micopt.enable'] = 1 if self.config.get('enabled', True) else 0
		params['micopt.meter_enable'] = 0
		text = presets.params_text(params)
		if text != self.params_text:
			# The host notices the new file and crossfades to it.
			os.makedirs(store.RUN_DIR, exist_ok=True)
			tmp = store.PARAMS_FILE + '.tmp'
			with open(tmp, 'w') as f:
				f.write(text)
			os.replace(tmp, store.PARAMS_FILE)
			self.params_text = text

	# --- bridge process ------------------------------------------------------------------

	def missing_files(self):
		return [p for p in (store.BRIDGE, store.HOST_EXE, store.APO_DLL) if not os.path.exists(p)]

	def start_bridge(self):
		missing = self.missing_files()
		if missing:
			self.last_error = 'Not installed: ' + ', '.join(os.path.basename(m) for m in missing)
			return
		env = dict(os.environ, WINEPREFIX=store.WINE_PREFIX, WINEDEBUG='-all',
		           # The APO enumerates audio devices while initialising; Wine's audio drivers
		           # make that hang, and the APO needs no real devices.
		           WINEDLLOVERRIDES='winepulse.drv,winealsa.drv,wineoss.drv=d;winemenubuilder.exe=d')
		cmd = [store.BRIDGE, '--max-latency', str(int(self.config.get('max_latency_ms', 40))), '--',
		       'wine', store.HOST_EXE, wine_path(store.APO_DLL), wine_path(store.PARAMS_FILE)]
		self.ready = False
		self.proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
		                             stderr=subprocess.PIPE, text=True, start_new_session=True)
		threading.Thread(target=self.read_bridge_output, args=(self.proc,), daemon=True).start()
		self.last_link_check = 0.0
		print(f'engine: started bridge pid {self.proc.pid}', flush=True)

	def read_bridge_output(self, proc):
		for line in proc.stderr:
			line = line.strip()
			if line.startswith('meter '):
				try:
					a, b = line.split()[1:3]
					self.meter = (float(a), float(b))
				except ValueError:
					pass
				continue
			if line.startswith('ready'):
				self.ready = True
				self.backoff = 2.0
				self.last_error = ''
			print(line, flush=True)

	def check_bridge(self):
		if self.proc and self.proc.poll() is not None:
			code = self.proc.returncode
			self.proc = None
			self.ready = False
			self.last_error = f'Processing stopped (exit {code}); restarting'
			self.next_start = time.monotonic() + self.backoff
			self.backoff = min(self.backoff * 2, MAX_BACKOFF)
		if not self.proc and time.monotonic() >= self.next_start:
			self.start_bridge()
			if not self.proc:
				self.next_start = time.monotonic() + MAX_BACKOFF

	def stop_bridge(self):
		if self.proc and self.proc.poll() is None:
			self.proc.terminate()
			try:
				self.proc.wait(timeout=5)
			except subprocess.TimeoutExpired:
				os.killpg(self.proc.pid, signal.SIGKILL)
		self.proc = None

	# --- links ---------------------------------------------------------------------------

	def check_links(self):
		objs = pw.dump()
		self.input = pw.pick_input(self.config.get('input', 'auto'), objs)
		dsp_in, dsp_out = f'{pw.DSP}:in', f'{pw.DSP}:out'
		mic_in = next((n for _, _, n in pw.ports(pw.VIRTUAL_MIC, 'in', objs)), None)
		if not pw.node_id(pw.DSP, objs) or not mic_in:
			return  # bridge still starting
		want = pw.capture_port(self.input['name'], objs) if self.input else None
		for port in pw.links_into(dsp_in, objs):
			if port != want:
				pw.unlink(port, dsp_in)
		if want and want not in pw.links_into(dsp_in, objs):
			pw.link(want, dsp_in)
		if dsp_out not in pw.links_into(mic_in, objs):
			pw.link(dsp_out, mic_in)
		if self.config.get('make_default') and not self.defaulted:
			pw.set_default_source(pw.VIRTUAL_MIC)
			self.defaulted = True

	# --- status --------------------------------------------------------------------------

	def publish(self):
		running = bool(self.proc and self.proc.poll() is None)
		state = 'running' if running and self.ready else 'starting' if running else 'error'
		store.write_status({
			'state': state,
			'error': self.last_error,
			'enabled': self.config.get('enabled', True),
			'input': self.input,
			'meter_in': self.meter[0] if self.ready else -120.0,
			'meter_out': self.meter[1] if self.ready else -120.0,
			'pid': os.getpid(),
			'updated': time.time(),
		})

	def run(self):
		signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
		signal.signal(signal.SIGINT, lambda *_: self.stop.set())
		while not self.stop.is_set():
			self.reload_config()
			self.check_bridge()
			now = time.monotonic()
			if self.proc and now - self.last_link_check >= LINK_EVERY:
				self.last_link_check = now
				self.check_links()
			self.publish()
			self.stop.wait(POLL)
		self.stop_bridge()
		store.write_status({'state': 'stopped', 'error': '', 'updated': time.time()})


if __name__ == '__main__':
	Engine().run()
