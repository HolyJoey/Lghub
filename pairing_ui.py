"""The "Pair a device" card for LIGHTSPEED receivers (pairing.py): on the receiver's page and in
Settings (once a device is on, the home screen shows the device instead of its receiver). Ours."""
from gi.repository import Gtk

import pairing
from ui import box, button_widget, label
from worker import Worker


def pair_card(receiver):
	c = box(spacing=10, css=['card'])
	c.append(label(f'Pair a device to this {receiver.name}', ['section-title']))
	c.append(label('Click Pair, then switch the new mouse or keyboard on (or press its connect button) within '
	               '30 seconds.', ['muted'], wrap=True))
	status = label('', ['muted', 'small'], wrap=True)
	worker = Worker()
	button = button_widget('Pair', ['apply'], lambda: start())
	button.set_halign(Gtk.Align.START)

	def done(slot):
		button.set_sensitive(True)
		status.set_text(f'Paired in slot {slot}. It shows up on the Devices page in a moment.' if slot
		                else 'Nothing paired: the receiver stopped waiting. Try again.')

	def failed(error):
		button.set_sensitive(True)
		status.set_text(f'Couldn’t talk to the receiver: {error}.')

	def start():
		button.set_sensitive(False)
		status.set_text('Waiting for a device… switch it on now.')
		worker.submit(lambda: pairing.pair(receiver), done, failed)
	c.append(button)
	c.append(status)
	return c


def receivers_card(found):
	"""Settings: a pair card per LIGHTSPEED receiver plugged in, or None when there's none."""
	receivers = [d for d in found if d.model.type == 'receiver' and pairing.can_pair(d)]
	if not receivers:
		return None
	c = box(spacing=12)
	for r in receivers:
		c.append(pair_card(r))
	return c
