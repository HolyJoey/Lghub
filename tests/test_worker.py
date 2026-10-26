"""The device thread (worker.py): jobs run in order off the main loop, results and errors come back on it,
and nothing comes back after stop()."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from gi.repository import GLib  # noqa: E402

import worker  # noqa: E402


def spin(until, seconds=2.0):
	ctx = GLib.MainContext.default()
	end = GLib.get_monotonic_time() + int(seconds * 1e6)
	while not until() and GLib.get_monotonic_time() < end:
		ctx.iteration(False)


class WorkerTest(unittest.TestCase):
	def test_results_errors_and_order(self):
		w = worker.Worker()
		self.addCleanup(w.stop)
		seen, main = [], threading.current_thread()
		w.submit(lambda: threading.current_thread() is not main, seen.append)
		w.submit(lambda: 1 / 0, None, lambda e: seen.append(type(e).__name__))
		w.submit(lambda: 'last', lambda r: seen.append((r, threading.current_thread() is main)))
		spin(lambda: len(seen) == 3)
		self.assertEqual(seen, [True, 'ZeroDivisionError', ('last', True)])

	def test_nothing_after_stop(self):
		w = worker.Worker()
		gate, seen = threading.Event(), []
		w.submit(gate.wait, seen.append)
		w.stop()
		gate.set()
		spin(lambda: False, 0.3)
		self.assertEqual(seen, [])


if __name__ == '__main__':
	unittest.main()
