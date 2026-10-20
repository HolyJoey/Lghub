"""Pairing a new device to a LIGHTSPEED receiver, as G HUB's HPP10Command::open_lock /
open_lock_LS2 / close_lock: HID++ 1.0 set register 0xB2 on the receiver, [action, 0, 0] with
action 1 = open the lock on LS1 receivers, 7 = open on LS2 receivers, 2 = close. Which receiver
is which comes from G HUB's receivers list. While the lock is open, a device that is switched on
or put in pairing mode pairs and the receiver sends its connection notice (0x41); the receiver
also reports its lock state (0x4A, bit 0 = open; from Logitech's HID++ 1.0 receiver spec).
How long to wait (G HUB's 30 s default lock time is the receiver's own) is ours.
"""
import time

import hidpp
import receiver_watch

LS1, LS2 = 1, 7
OPEN = {'046d:c539': LS1, '046d:c53f': LS1, '046d:c53d': LS1,
        '046d:c541': LS2, '046d:c545': LS2, '046d:c547': LS2, '046d:c54d': LS2, '046d:c543': LS2}
CLOSE = 2
LOCK_STATUS = 0x4A
WAIT = 30.0


def can_pair(receiver):
	return receiver.usb_id in OPEN


def lock_request(action):
	"""Set register 0xB2 on the receiver itself (device index 0xFF)."""
	return bytes([hidpp.SHORT, 0xFF, 0x80, 0xB2, action, 0, 0])


def wait_for_pairing(transport, deadline, clock=time.monotonic):
	"""The device index that connected while the lock was open, or None (closed or timed out)."""
	opened = False
	while clock() < deadline:
		report = transport.read(0.5)
		if not report:
			continue
		index = receiver_watch.connected(report)
		if index is not None:
			return index
		if len(report) >= 4 and report[0] == hidpp.SHORT and report[2] == LOCK_STATUS:
			if report[3] & 1:
				opened = True
			elif opened:
				return None          # the receiver closed the lock: nothing paired in time
	return None


def pair(receiver, wait=WAIT, clock=time.monotonic):
	"""Opens the receiver's lock for a new device, waits for one, closes it again. The new device's
	slot, or None. Blocks: call from a worker."""
	import devices
	transport, _reports = devices.receiver_transport(receiver)
	try:
		transport.write(lock_request(OPEN[receiver.usb_id]))
		return wait_for_pairing(transport, clock() + wait, clock)
	finally:
		try:
			transport.write(lock_request(CLOSE))
		finally:
			transport.close()
