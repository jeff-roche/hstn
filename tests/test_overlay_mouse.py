"""Mouse and controller navigation share the overlay's selected button."""
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class OverlayMouseTest(unittest.TestCase):
    def test_hover_tracks_selection_without_activating_and_preserves_clicks(self):
        code = r'''
import importlib.util,os
from pathlib import Path
from unittest import mock
spec=importlib.util.spec_from_file_location('overlay',Path('src/session-overlay.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
menu=m.Overlay(desktop=True);menu.show();app.processEvents()
menu.choose=mock.Mock()
def enter(index):
 app.sendEvent(menu.buttons[index],m.QtCore.QEvent(m.QtCore.QEvent.Enter))
def selected(index):
 assert menu.selection==index,(menu.selection,index)
 assert [bool(b.property('selected')) for b in menu.buttons]==[i==index for i in range(4)]
enter(1);selected(1);menu.choose.assert_not_called()
menu.navigate(1);selected(2)
# Moving within the same hovered button must regain selection after controller use.
move=m.QtGui.QMouseEvent(m.QtCore.QEvent.MouseMove,m.QtCore.QPointF(10,10),m.QtCore.QPointF(10,10),m.QtCore.Qt.NoButton,m.QtCore.Qt.NoButton,m.QtCore.Qt.NoModifier)
app.sendEvent(menu.buttons[1],move);selected(1)
menu.buttons[2].setEnabled(False);enter(2);selected(1)
menu.buttons[3].hide();enter(3);selected(1)
menu.buttons[1].click();menu.choose.assert_called_once_with(1)
menu.hide()
print('OVERLAY_MOUSE_PASS')
'''
        result=subprocess.run(['/usr/bin/python3','-B','-c',code],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('OVERLAY_MOUSE_PASS',result.stdout)
