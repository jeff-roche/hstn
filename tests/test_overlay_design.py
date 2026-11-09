"""Launch Deck layout and guarded interactions at handheld and TV sizes."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OverlayDesignTest(unittest.TestCase):
    def test_responsive_review_navigation_and_packaged_assets(self):
        code = r'''
import importlib.util, json, os
from pathlib import Path
from unittest import mock

def load(path):
 spec=importlib.util.spec_from_file_location('design_overlay',path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module
m=load(Path('src/session-overlay.py').resolve())
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
for width,height in [(854,480),(1280,800),(1920,1080)]:
 with mock.patch.dict(os.environ,{'SESSION_SWITCH_CURRENT_SESSION':'heroic'}):
  menu=m.Overlay()
 menu.resize(width,height);menu.show();app.processEvents()
 assert menu.size()==m.QtCore.QSize(width,height)
 assert menu.panel.width()<=960 and menu.panel.height()<=620
 for name in ('cross','circle'):
  icon=menu.footer.glyphs[name];text=menu.footer.labels[name]
  assert abs(icon.mapTo(menu,icon.rect().center()).y()-text.mapTo(menu,text.rect().center()).y())<=1
 # Prompts follow the physical controller family, then real keyboard navigation.
 assert menu.input_family=='keyboard'
 for family, words in [('xbox','A: select. B: back.'),('playstation','Cross: select. Circle: back.')]:
  menu.set_input_family(family)
  assert menu.footer.accessibleName()==words
  assert all(not label.pixmap().isNull() for label in menu.footer.glyphs.values())
  app.processEvents()
  if width==1280:
   menu.grab().save('/tmp/hstn-glyphs-'+family+'.png')
 menu.set_input_family('keyboard');app.processEvents()
 if width==1280:
  menu.grab().save('/tmp/hstn-glyphs-keyboard.png')
 assert menu.buttons[1].current and not menu.buttons[0].current
 assert menu.active_indices()==[0,1,2]
 assert all(not b.art.isNull() for b in menu.buttons)
 assert not menu.logo_art.isNull()
 assert not menu.windowIcon().isNull()
 for index in range(2):
  assert menu.buttons[index].geometry().right()<menu.buttons[index+1].geometry().left()
 # Qt delivers Tab through event(), rather than keyPressEvent().
 app.sendEvent(menu,m.QtGui.QKeyEvent(m.QtCore.QEvent.KeyPress,m.QtCore.Qt.Key_Tab,m.QtCore.Qt.NoModifier))
 assert menu.selection==1 and menu.input_family=='keyboard'
 menu.set_input_family('xbox')
 app.sendEvent(menu,m.QtGui.QKeyEvent(m.QtCore.QEvent.KeyPress,m.QtCore.Qt.Key_Left,m.QtCore.Qt.NoModifier))
 assert menu.input_family=='keyboard' and menu.selection==0
 menu.planner=mock.Mock();menu.planner.busy=False
 menu.request=mock.Mock();menu.request.busy=False;menu.closer=mock.Mock()
 menu.choose(0);menu.choose(0);assert menu.planner.start.call_count==1
 plan={'path':'/tmp/nonexistent-hstn-review','apps':[{'label':f'Game <{i}>','processes':[{'name':f'game-{i}.exe'}]} for i in range(40)],'warnings':['unknown']}
 menu.plan_finished(0,json.dumps(plan));app.processEvents()
 assert menu.selection==1 and menu.active_indices()==[0,1]
 assert menu.status.textFormat()==m.QtCore.Qt.RichText and 'Game &lt;0&gt;' in menu.status.text()
 assert 'could not be identified' in menu.status.text()
 bar=menu.status_scroll.verticalScrollBar();assert bar.maximum()>0
 menu.scroll_details(1);assert bar.value()>0
 for family, scroll in [('keyboard','Page Up'),('xbox','LB or RB'),('playstation','L1 or R1')]:
  menu.set_input_family(family)
  assert scroll in menu.footer.accessibleName()
  assert not menu.footer.scroll.isHidden()
 for button in menu.buttons[:2]:
  position=button.mapTo(menu,m.QtCore.QPoint(0,0))
  assert position.y()+button.height()<menu.height()
  assert button.isVisible() and button.isEnabled()
 menu.cancel_or_hide();assert menu.mode=='menu'
 menu.request.start.assert_not_called();menu.closer.start.assert_not_called()
 app.processEvents()
 # Reset restores the deck below the title and helper below the destination row.
 deck_bottom=menu.deck.mapTo(menu,m.QtCore.QPoint(0,menu.deck.height())).y()
 assert menu.status_scroll.mapTo(menu,m.QtCore.QPoint()).y()>=deck_bottom
 menu.choose(2);menu.plan_finished(0,json.dumps(plan));assert menu.selection==1
 menu.navigate(-1);menu.choose(menu.selection);menu.choose(0)
 menu.closer.start.assert_called_once_with('desktop',arguments=['execute',plan['path']])
 menu.switch_finished(24,'Apps changed');assert 'review them again' in menu.status.text()
 menu.choose(0);menu.plan_finished(0,json.dumps({'apps':[]}))
 menu.request.start.assert_called_once_with('steam')
 menu.switch_finished(21,'Inspection failed');assert 'failed' in menu.status.text()
 menu.hide()
with mock.patch.dict(os.environ,{'SESSION_SWITCH_CURRENT_SESSION':''}):
 menu=m.Overlay();assert not any(b.current for b in menu.buttons[:3])
menu.hide()
# Assets must be included in both standalone and native inventory.
spec=importlib.util.spec_from_file_location('package',Path('installer/package.py'))
package=importlib.util.module_from_spec(spec);spec.loader.exec_module(package)
inventory=package.inventory(Path.cwd())
for name in ('assets/controller/xbox-a.svg','assets/controller/xbox-b.svg','assets/controller/xbox-lb.svg','assets/controller/xbox-rb.svg','assets/controller/keyboard-enter.svg','assets/controller/keyboard-escape.svg','assets/controller/keyboard-page-up.svg','assets/controller/keyboard-page-down.svg','assets/logo/hstn-rocket-256.png','assets/controller/cross.svg','assets/controller/circle.svg','assets/controller/l1.svg','assets/controller/r1.svg'):
 assert name in inventory
 assert not m.QtGui.QPixmap(str(Path(name))).isNull(),name
print('DESIGN_PASS')
'''
        result = subprocess.run(['/usr/bin/python3', '-B', '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('DESIGN_PASS', result.stdout)
