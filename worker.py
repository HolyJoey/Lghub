"""Device I/O off the GTK main loop: one thread per device runs jobs in order, results come
back on the main loop."""
import queue
import threading

from gi.repository import GLib


class Worker:
	def __init__(self):
		self._jobs = queue.Queue()
		self._stopped = False
		threading.Thread(target=self._run, daemon=True).start()

	def submit(self, job, done=None, failed=None):
		"""Run job() on the device thread; then done(result) or failed(exception) on the
		main loop."""
		self._jobs.put((job, done, failed))

	def stop(self):
		self._stopped = True
		self._jobs.put(None)

	def _run(self):
		while (item := self._jobs.get()) is not None:
			job, done, failed = item
			try:
				result = job()
			except Exception as e:  # noqa: BLE001 - every device error goes back to the page
				self._post(failed, e)
				continue
			self._post(done, result)

	def _post(self, callback, value):
		if callback and not self._stopped:
			GLib.idle_add(lambda: callback(value) and False)
