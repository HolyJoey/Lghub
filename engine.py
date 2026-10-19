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

import bv2_presets
import eq
import inputd
import hotplug
import presets
import battery_watch
import lightsync
import osd
import profiles
import restore
import pw
import store
import surround
import tray
import webcam

POLL = 0.25          # config / status interval while an app records, seconds
IDLE_POLL = 1.0      # the same while idle (link events still wake the loop at once)
LINK_EVERY = 60.0    # fallback; link events and sound-card hotplug trigger a check at once
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
		self.bv2_text = None
		self.kind = None             # the bridge's DSP: 'micopt' (Blue VO!CE) or 'bv2' (Blue VO!CE 2)
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
		self.sound_cards = hotplug.Watch(hotplug.SOUND)
		self.inputs = inputd.Manager()
		self.games = profiles.Switcher()
		self.restorer = restore.Restorer()
		self.lightsync = lightsync.Runner()
		self.battery = battery_watch.Watch()
		self.osd = osd.Watch()
		self.tray = tray.Tray(self.tray_devices) if store.load_config().get('tray', True) else None
		self.game = None
		self.mic_gain = None         # (mic, gain) last set for Blue VO!CE 2

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
		text = bv2_presets.params_text(self.config.get('bv2_params', {}), self.config.get('enabled', True))
		if text != self.bv2_text:
			os.makedirs(store.RUN_DIR, exist_ok=True)
			with open(store.BV2_PARAMS_FILE + '.tmp', 'w') as f:
				f.write(text)
			os.replace(store.BV2_PARAMS_FILE + '.tmp', store.BV2_PARAMS_FILE)
			self.bv2_text = text

	# --- bridge process ------------------------------------------------------------------

	def wanted_kind(self):
		"""Blue VO!CE 2 for the mics G HUB runs it on (Yetis, G735), Blue VO!CE otherwise."""
		if self.input and pw.is_bv2_mic(self.input) and os.path.exists(store.BV2_DLL):
			return 'bv2'
		return 'micopt'

	def missing_files(self, kind):
		dll = store.BV2_DLL if kind == 'bv2' else store.APO_DLL
		return [p for p in (store.BRIDGE, dll) if not os.path.exists(p)]

	def start_bridge(self):
		kind = self.wanted_kind()
		missing = self.missing_files(kind)
		if missing:
			self.last_error = 'Not installed: ' + ', '.join(os.path.basename(m) for m in missing)
			return
		if kind == 'bv2':
			cmd = [store.BRIDGE, '--dll', store.BV2_DLL, '--params', store.BV2_PARAMS_FILE, '--engine', 'bv2']
		else:
			cmd = [store.BRIDGE, '--dll', store.APO_DLL, '--params', store.PARAMS_FILE]
		self.kind = kind
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
		if self.wanted_kind() != self.kind:
			print(f'engine: switching to {self.wanted_kind()} for {self.input and self.input["name"]}', flush=True)
			self.stop_bridge()          # check_bridge starts the right one next round
			self.ready = False
			return
		mic_in = next((n for _, _, n in pw.ports(pw.VIRTUAL_MIC, 'in', objs)), None)
		if not pw.node_id(pw.DSP, objs) or not mic_in:
			return  # bridge still starting
		now = time.monotonic()
		if pw.links_out_of(pw.VIRTUAL_MIC, objs):
			self.last_listener = now
		self.listening = now - self.last_listener < IDLE_GRACE
		self.link_input(objs)
		self.link_output(objs, mic_in)
		self.apply_mic_gain(objs)
		if self.config.get('make_default') and not self.defaulted:
			pw.set_default_source(pw.VIRTUAL_MIC)
			self.defaulted = True

	def apply_mic_gain(self, objs):
		"""Blue VO!CE 2 presets carry the mic's own gain (G HUB's inputGain); set it on the mic."""
		gain = self.config.get('bv2_params', {}).get(bv2_presets.MIC_GAIN)
		if self.kind != 'bv2' or gain is None or not self.input:
			return
		want = (self.input['name'], gain)
		if want != self.mic_gain and pw.set_volume(self.input['name'], float(gain), objs):
			self.mic_gain = want

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
			'voice': self.kind,
			'game': self.game,
			'listening': self.listening,
			'meter_in': self.meter[0] if self.ready and self.listening else -120.0,
			'meter_out': self.meter[1] if self.ready and self.listening else -120.0,
			'pid': os.getpid(),
			'updated': time.time(),
		})

	def voice_round(self, now):
		"""Links and status for Blue VO!CE."""
		if self.sound_cards.changed():      # a headset or mic came or went: look again now
			self.last_link_check = 0.0
			self.eq.last_check = 0.0
			self.surround.wake = True
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

	def other_rounds(self, now):
		"""Equalizer, surround, webcams, software buttons and game profiles, each when due."""
		if self.eq.due() or self.surround.due():
			objs = pw.dump()
			self.eq.check(objs)
			self.surround.check(objs)
		if self.webcams.due():
			self.webcams.check()
		if self.inputs.due():
			self.inputs.check()
		if self.games.due(now):
			self.game = self.games.check(now)
		if self.restorer.due(now):
			self.restorer.check(now)
		if self.lightsync.due(now):
			self.lightsync.check(now)
		if self.battery.due(now):
			self.battery.check(now)
			if self.tray:
				self.tray.refresh()
		if self.osd.due(now):
			self.osd.check(now)

	def tray_devices(self):
		"""[(name, battery reading or None)] for the tray: what's plugged in, and the wireless devices
		the battery watch last read."""
		import devices
		readings = dict(self.battery.readings)
		out = []
		for d in devices.discover():
			if d.model.type != 'receiver':
				out.append((d.name, readings.pop(d.id, (None, None))[1]))
		out += list(readings.values())
		return out

	def run(self):
		signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
		signal.signal(signal.SIGINT, lambda *_: self.stop.set())
		threading.Thread(target=self.watch_links, daemon=True).start()
		if self.tray:
			self.tray.start()
		while not self.stop.is_set():
			self.reload_config()
			self.check_bridge()
			now = time.monotonic()
			self.voice_round(now)
			self.other_rounds(now)
			self.link_event.wait(POLL if self.listening else IDLE_POLL)
		self.stop_bridge()
		self.inputs.stop()
		self.lightsync.stop()
		self.osd.stop()
		if self.tray:
			self.tray.stop()
		self.surround.stop()
		self.eq.stop()
		store.write_status({'state': 'stopped', 'error': '', 'updated': time.time()})


if __name__ == '__main__':
	Engine().run()
