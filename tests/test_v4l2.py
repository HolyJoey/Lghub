"""Webcam controls through V4L2 (a fake driver answering the ioctls) and putting them back."""
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import v4l2  # noqa: E402
import webcam  # noqa: E402

DISABLED = 0x0001


class FakeDriver:
	"""Controls: id -> (type, name, min, max, step, default, flags, value, menu)."""

	def __init__(self):
		self.controls = {
			0x980900: (v4l2.T_INTEGER, b'Brightness', 0, 255, 1, 128, 0, 100, None),
			0x980901: (v4l2.T_INTEGER, b'Hidden', 0, 1, 1, 0, DISABLED, 0, None),
			0x9a0901: (v4l2.T_MENU, b'Auto Exposure', 0, 3, 1, 3, 0, 3, {1: b'Manual Mode', 3: b'Aperture Priority'}),
			0x9a0902: (v4l2.T_INTEGER_MENU, b'Zoom Steps', 0, 1, 1, 0, 0, 0, {0: 100, 1: 200}),
			0x980910: (6, b'A button', 0, 0, 0, 0, 0, 0, None),                       # a button: skipped
		}
		self.set_log = []

	def ioctl(self, _fd, request, buf):
		if request == v4l2.VIDIOC_QUERYCTRL:
			cid = struct.unpack_from('=I', buf)[0]
			ids = sorted(self.controls)
			nxt = [i for i in ids if i > (cid & ~v4l2.NEXT_CTRL)] if cid & v4l2.NEXT_CTRL else [cid]
			if not nxt or nxt[0] not in self.controls:
				raise OSError(22, 'EINVAL')
			kind, name, low, high, step, default, flags, _v, _m = self.controls[nxt[0]]
			buf[:] = v4l2._QUERYCTRL.pack(nxt[0], kind, name, low, high, step, default, flags)
		elif request == v4l2.VIDIOC_QUERYMENU:
			cid, index = struct.unpack_from('=II', buf)
			menu = self.controls[cid][8]
			if index not in menu:
				raise OSError(22, 'EINVAL')
			item = menu[index]
			raw = struct.pack('=q', item).ljust(32, b'\0') if isinstance(item, int) else item
			buf[:] = struct.pack('=II32sI', cid, index, raw, 0)
		elif request == v4l2.VIDIOC_G_CTRL:
			cid = struct.unpack_from('=I', buf)[0]
			buf[:] = v4l2._CONTROL.pack(cid, self.controls[cid][7])
		elif request == v4l2.VIDIOC_S_CTRL:
			self.set_log.append(v4l2._CONTROL.unpack(buf))
		else:
			raise OSError(25, 'ENOTTY')


class CameraTest(unittest.TestCase):
	def test_controls_menus_and_values(self):
		driver = FakeDriver()
		with mock.patch('os.open', return_value=3), mock.patch('fcntl.ioctl', driver.ioctl), mock.patch('os.close'):
			cam = v4l2.Camera('/dev/video9')
			controls = {c.key: c for c in cam.controls()}
			cam.set(0x980900, 50)
			cam.close()
		self.assertEqual(sorted(controls), ['auto_exposure', 'brightness', 'zoom_steps'])
		self.assertEqual(controls['brightness'].value, 100)
		self.assertEqual(controls['auto_exposure'].menu, {1: 'Manual Mode', 3: 'Aperture Priority'})
		self.assertEqual(controls['zoom_steps'].menu, {0: '100', 1: '200'})
		self.assertEqual(driver.set_log, [(0x980900, 50)])

	def test_video_node(self):
		with tempfile.TemporaryDirectory() as root:
			for name, port, index in (('video1', '3-4', '1'), ('video0', '3-4', '0'), ('video2', '3-5', '0')):
				dev = os.path.join(root, 'devices', port + ':1.0', name)
				os.makedirs(dev)
				os.makedirs(os.path.join(root, 'class', name))
				os.symlink(dev, os.path.join(root, 'class', name, 'device'))
				with open(os.path.join(root, 'class', name, 'index'), 'w') as f:
					f.write(index)
			with mock.patch.object(v4l2, 'SYS_VIDEO', os.path.join(root, 'class')):
				self.assertEqual(v4l2.video_node('3-4'), '/dev/video0')
				self.assertIsNone(v4l2.video_node('9-9'))
		with mock.patch.object(v4l2, 'SYS_VIDEO', '/nonexistent'):
			self.assertIsNone(v4l2.video_node('3-4'))


class RestorerTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		patcher = mock.patch.object(webcam, 'WEBCAM_FILE', os.path.join(self.tmp.name, 'webcams.json'))
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(self.tmp.cleanup)
		self.cam = mock.Mock(id='usb:3-4', usb_id='046d:082d', serial='AB', model=mock.Mock(type='camera'))
		self.cam.name = 'C920'

	def test_remember_and_forget(self):
		webcam.remember(self.cam, 'brightness', 140)
		self.assertEqual(webcam.saved(self.cam), {'brightness': 140})
		self.assertEqual(webcam.ident(self.cam), '046d:082d:AB')
		webcam.forget(self.cam)
		webcam.forget(self.cam)
		self.assertEqual(webcam.saved(self.cam), {})

	def test_settings_go_back_after_the_camera_settles(self):
		webcam.remember(self.cam, 'brightness', 140)
		with mock.patch('hotplug.Watch'):
			r = webcam.Restorer()
		opened = mock.Mock()
		with mock.patch('devices.discover', return_value=[self.cam]), \
				mock.patch.object(webcam.v4l2, 'video_node', return_value='/dev/video0'), \
				mock.patch.object(webcam.v4l2, 'Camera', return_value=opened), \
				mock.patch.object(webcam, 'apply') as apply_, mock.patch('time.monotonic', side_effect=[10.0, 12.0, 13.0]):
			r.check()                                   # just plugged in: let it settle
			self.assertFalse(apply_.called)
			r.check()
			r.check()                                   # done: not again
		apply_.assert_called_once_with(opened, {'brightness': 140})
		opened.close.assert_called_once()
		with mock.patch('devices.discover', return_value=[]), mock.patch('time.monotonic', return_value=20.0):
			r.check()                                   # unplugged: forgotten, done again when back
		self.assertEqual((r.seen, r.done), ({}, set()))

	def test_nothing_saved(self):
		with mock.patch('hotplug.Watch'):
			r = webcam.Restorer()
		with mock.patch('devices.discover', return_value=[self.cam]), \
				mock.patch.object(webcam.v4l2, 'Camera') as camera:
			r.check()
		self.assertFalse(camera.called)
		self.assertIn('usb:3-4', r.done)


if __name__ == '__main__':
	unittest.main()
