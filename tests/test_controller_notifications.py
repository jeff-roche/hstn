"""Physical hotplug notices and non-interactive toast lifecycle."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ControllerNotificationsTest(unittest.TestCase):
    def test_connections_and_toasts_preserve_focus_and_menu_input(self):
        code = r'''
import importlib.util, os
from unittest import mock
os.environ['QT_QPA_PLATFORM']='offscreen'
spec=importlib.util.spec_from_file_location('notification_overlay','src/session-overlay.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
usb={'name':'Xbox controller','transport':'usb'}
bt={'name':'Xbox controller','transport':'bluetooth'}
sony={'name':'DualSense controller','transport':'bluetooth'}
snapshot=mock.Mock(return_value={'usb':usb, 'sony':sony})
monitor=m.ControllerConnections(snapshot)
events=[]
monitor.changed.connect(lambda *event:events.append(event))
monitor.refresh();assert not events
snapshot.return_value={'sony':sony,'bt':bt}
monitor.refresh()
assert events==[('Xbox controller','usb',False),('Xbox controller','bluetooth',True)]
monitor.refresh();assert len(events)==2
snapshot.return_value={}
monitor.refresh();assert len(events)==4
# A toast never asks the router to capture input or activates a window.
toast=m.ControllerToast(desktop=True)
with mock.patch.object(toast,'activateWindow') as activate:
 toast.notify('Xbox controller','bluetooth',True)
 app.processEvents()
 assert toast.isVisible() and toast.timer.isActive()
 assert toast.message.text()=='Xbox controller\nConnected'
 assert toast.transport.accessibleName()=='Bluetooth'
 assert not toast.transport.pixmap().isNull() and not toast.rocket.pixmap().isNull()
 assert toast.width()<=360 and toast.height()==76
 assert toast.rocket.geometry().right()<toast.message.geometry().left()
 assert toast.message.geometry().right()<toast.transport.geometry().left()
 assert toast.testAttribute(m.QtCore.Qt.WA_ShowWithoutActivating)
 assert toast.testAttribute(m.QtCore.Qt.WA_TranslucentBackground)
 assert toast.windowFlags() & m.QtCore.Qt.WindowDoesNotAcceptFocus
 assert toast.windowFlags() & m.QtCore.Qt.WindowTransparentForInput
 assert toast.focusPolicy()==m.QtCore.Qt.NoFocus
 area=app.primaryScreen().availableGeometry()
 assert area.contains(toast.geometry())
 image=toast.grab().toImage()
 assert image.hasAlphaChannel()
 for x,y in [(0,0),(image.width()-1,0),(0,image.height()-1),(image.width()-1,image.height()-1)]:
  assert image.pixelColor(x,y).alpha()==0
 assert image.pixelColor(image.width()//2,image.height()-6).getRgb()==(7,23,46,255)
 image.save('/tmp/hstn-controller-toast.png')
 toast.notify('Xbox controller','bluetooth',False)
 assert toast.message.text()=='Xbox controller\nConnected'
 toast.advance()
 assert toast.message.text()=='Xbox controller\nDisconnected'
 toast.advance();assert not toast.isVisible() and not toast.timer.isActive()
 activate.assert_not_called()
# Gamescope tagging must explicitly decline focus, and must be cleared on hide.
toast=m.ControllerToast(desktop=False)
with mock.patch.object(m,'xproperty') as tag:
 toast.notify('DualSense controller','usb',True)
 values=[call.args[1:] for call in tag.call_args_list]
 assert ('STEAM_INPUT_FOCUS',0) in values and ('STEAM_OVERLAY',1) in values
 assert ('STEAM_INPUT_FOCUS',1) not in values
 assert toast.transport.accessibleName()=='USB' and not toast.transport.pixmap().isNull()
 app.processEvents()
 image=toast.grab().toImage()
 assert image.pixelColor(0,0).alpha()==0
 image.save('/tmp/hstn-controller-toast-usb.png')
 toast.dismiss()
 assert tag.call_args.args[1:]==('STEAM_OVERLAY',0)
# Rapid reconnects cannot grow an unbounded notification backlog.
toast=m.ControllerToast(desktop=True)
for _ in range(20):toast.notify('Xbox controller','usb',True)
assert len(toast.pending)<=6
toast.dismiss()
print('NOTIFICATIONS_PASS')
'''
        result = subprocess.run(['/usr/bin/python3', '-B', '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('NOTIFICATIONS_PASS', result.stdout)
