#!/usr/bin/env python3
"""Lghub engine: keeps the Blue VO!CE virtual microphone and the headset equalizer running, and
puts webcam settings back when a camera is plugged in.

Runs bluevoice-bridge (Logitech's Blue VO!CE DSP as a native PipeWire filter), keeps the links
mic -> bluevoice_dsp -> "Blue VO!CE Microphone" in place, applies config.json changes live, and
publishes status.json for the app. Meant to run as a systemd user service.
"""
import os
import signal
import subprocess
import threading
import time

import eq
import presets
import pw
import store
import surround
import webcam

POLL = 0.25          # config / status interval, seconds
LINK_EVERY = 5.0     # full link check interval, seconds (link events also trigger a check at once)
IDLE_STATUS_EVERY = 1.0  # status.json interval while no app listens (meters need 10 Hz only when used)
IDLE_GRACE = 5.0     # release the real mic this long after the last app stops recording
MAX_BACKOFF = 30.0


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
		self.listening = False       # some app records from the virtual mic
		self.last_listener = 0.0
		self.link_event = threading.Event()
		self.last_publish = 0.0
		self.eq = eq.Runner()
		self.webcams = webcam.Restorer()
		self.surround = surround.Runner()

	# --- configuration -------------------------------------------------------------------

	def reload_config(self):
		try:
			mtime = os.stat(store.CONFIG_FILE).st_mtime
		except FileNotFoundError:
			mtime = None
		if mtime == self.config_mtime and self.params_text is not None:
			return
		old_input = self.config.get('input')
		self.config_mtime = mtime
		self.config = store.load_config()
		if self.config.get('input') != old_input:
			self.last_link_check = 0.0  # relink now
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
		return [p for p in (store.BRIDGE, store.APO_DLL) if not os.path.exists(p)]

	def start_bridge(self):
		missing = self.missing_files()
		if missing:
			self.last_error = 'Not installed: ' + ', '.join(os.path.basename(m) for m in missing)
			return
		cmd = [store.BRIDGE, '--dll', store.APO_DLL, '--params', store.PARAMS_FILE]
		self.ready = False
		self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
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

	def watch_links(self):
		"""Wake the main loop whenever an app starts or stops recording from the virtual mic."""
		while not self.stop.is_set():
			try:
				mon = subprocess.Popen(['pw-link', '-m', '-l'], stdout=subprocess.PIPE, text=True)
			except OSError:
				return
			for line in mon.stdout:
				if self.stop.is_set():
					break
				self.on_link_change(line)
			mon.kill()
			self.stop.wait(2)

	def on_link_change(self, line):
		"""A line from pw-link -m: '+' or '-' and the link."""
		if line[:1] not in '+-':
			return
		if pw.VIRTUAL_MIC + ':' in line:
			self.link_event.set()
		if surround.SINK + ':playback' in line:
			self.surround.wake = True     # an app started or stopped playing into surround
			self.link_event.set()

	def check_links(self):
		"""The real mic and the virtual mic are only linked while some app records from the
		virtual one, so the mic isn't kept open (and its in-use light on) and nothing runs idle."""
		objs = pw.dump()
		self.input = pw.pick_input(self.config.get('input', 'auto'), objs)
		mic_in = next((n for _, _, n in pw.ports(pw.VIRTUAL_MIC, 'in', objs)), None)
		if not pw.node_id(pw.DSP, objs) or not mic_in:
			return  # bridge still starting
		now = time.monotonic()
		if pw.links_out_of(pw.VIRTUAL_MIC, objs):
			self.last_listener = now
		self.listening = now - self.last_listener < IDLE_GRACE
		self.link_input(objs)
		self.link_output(objs, mic_in)
		if self.config.get('make_default') and not self.defaulted:
			pw.set_default_source(pw.VIRTUAL_MIC)
			self.defaulted = True

	def link_input(self, objs):
		"""Exactly the chosen microphone into the DSP while listening; nothing otherwise."""
		dsp_in = f'{pw.DSP}:in'
		want = pw.capture_port(self.input['name'], objs) if self.input and self.listening else None
		for port in pw.links_into(dsp_in, objs):
			if port != want:
				pw.unlink(port, dsp_in)
		if want and want not in pw.links_into(dsp_in, objs):
			pw.link(want, dsp_in)

	def link_output(self, objs, mic_in):
		dsp_out = f'{pw.DSP}:out'
		fed = dsp_out in pw.links_into(mic_in, objs)
		if self.listening and not fed:
			pw.link(dsp_out, mic_in)
		elif not self.listening and fed:
			pw.unlink(dsp_out, mic_in)

	# --- status --------------------------------------------------------------------------

	def publish(self):
		running = bool(self.proc and self.proc.poll() is None)
		if not running:
			state = 'error'
		elif self.ready:
			state = 'running'
		else:
			state = 'starting'
		store.write_status({
			'state': state,
			'error': self.last_error,
			'enabled': self.config.get('enabled', True),
			'input': self.input,
			'listening': self.listening,
			'meter_in': self.meter[0] if self.ready and self.listening else -120.0,
			'meter_out': self.meter[1] if self.ready and self.listening else -120.0,
			'pid': os.getpid(),
			'updated': time.time(),
		})

	def run(self):
		signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
		signal.signal(signal.SIGINT, lambda *_: self.stop.set())
		threading.Thread(target=self.watch_links, daemon=True).start()
		while not self.stop.is_set():
			self.reload_config()
			self.check_bridge()
			now = time.monotonic()
			due = now - self.last_link_check >= LINK_EVERY
			if self.proc and (due or self.link_event.is_set()):
				self.link_event.clear()
				self.last_link_check = now
				self.check_links()
			if self.listening or now - self.last_publish >= IDLE_STATUS_EVERY:
				self.last_publish = now
				self.publish()
			if not self.proc:
				self.link_event.clear()  # nothing to relink until the bridge is back
			eq_due, surround_due = self.eq.due(), self.surround.due()
			if eq_due or surround_due:
				objs = pw.dump()
				self.eq.check(objs)
				self.surround.check(objs)
			if self.webcams.due():
				self.webcams.check()
			self.link_event.wait(POLL)
		self.stop_bridge()
		self.surround.stop()
		self.eq.stop()
		store.write_status({'state': 'stopped', 'error': '', 'updated': time.time()})


if __name__ == '__main__':
	Engine().run()
