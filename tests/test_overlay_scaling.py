"""Backend selection and density-aware artwork at fractional and integer scales."""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scaling_overlay', ROOT/'src/session-overlay.py')
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)


class OverlayScalingTest(unittest.TestCase):
    def test_desktop_wayland_and_gamescope_x11_are_selected_independently(self):
        env = {'WAYLAND_DISPLAY': 'wayland-0', 'SESSION_SWITCH_DESKTOP_MODE': '1'}
        self.assertEqual(overlay.qt_platform(env, []), 'wayland')
        self.assertEqual(overlay.qt_platform({'WAYLAND_DISPLAY': 'wayland-0'}, ['--desktop']), 'wayland')
        self.assertEqual(overlay.qt_platform({**env, 'QT_QPA_PLATFORM': 'offscreen'}, []), 'offscreen')
        self.assertEqual(overlay.qt_platform({'SESSION_SWITCH_DESKTOP_MODE': '1'}, []), 'xcb')
        self.assertEqual(overlay.qt_platform({'WAYLAND_DISPLAY': 'gamescope-0', 'QT_QPA_PLATFORM': 'wayland'}, []), 'xcb')

    def test_fractional_gaming_scale_renders_at_native_pixel_resolution(self):
        code = r'''
import importlib.util,os
from pathlib import Path
spec=importlib.util.spec_from_file_location('fractional_overlay',Path('src/session-overlay.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
menu=m.Overlay();menu.resize(1280,800);menu.show();app.processEvents()
menu.set_input_family('handheld');app.processEvents()
assert menu.devicePixelRatioF()==1.5
assert menu.grab().size()==m.QtCore.QSize(1920,1200)
assert menu.logo.pixmap().devicePixelRatio()==1.5
assert menu.panel.size()==m.QtCore.QSize(720,465)
assert all(glyph.pixmap().devicePixelRatio()==1.5 for glyph in menu.footer.glyphs.values())
menu.hide()
print('FRACTIONAL_PASS')
'''
        env = {**os.environ, 'QT_SCALE_FACTOR': '1.5', 'QT_QPA_PLATFORM': 'offscreen'}
        result = subprocess.run(['/usr/bin/python3','-B','-c',code], cwd=ROOT, env=env,
                                capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr+result.stdout)
        self.assertIn('FRACTIONAL_PASS',result.stdout)

    def test_high_density_assets_keep_logical_sizes_and_render_valid_menu(self):
        code = r'''
import importlib.util,os
from pathlib import Path
spec=importlib.util.spec_from_file_location('scaling_overlay',Path('src/session-overlay.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
for ratio in (1,1.9,2):
 source=m.QtGui.QPixmap(256,256);source.fill(m.QtGui.QColor('#FFF5E2'))
 result=m.scaled_art(source,m.QtCore.QSize(40,30),ratio)
 assert result.devicePixelRatio()==ratio
 assert abs(result.deviceIndependentSize().height()-30)<1
 assert result.width()==round(30*ratio)
menu=m.Overlay(desktop=True);menu.resize(1011,632);menu.show();app.processEvents()
menu.set_input_family('handheld');app.processEvents()
ratio=menu.devicePixelRatioF()
assert ratio==2,ratio
assert menu.logo.pixmap().devicePixelRatio()==ratio
for glyph in menu.footer.glyphs.values():
 assert not glyph.pixmap().isNull()
 assert glyph.pixmap().devicePixelRatio()==ratio
 assert glyph.pixmap().width()>=glyph.width()*ratio-1
assert menu.panel.width()<menu.width() and menu.panel.height()<menu.height()
assert menu.grab().size()==m.QtCore.QSize(2022,1264)
menu.grab().save('/tmp/hstn-gos-hidpi-fixture.png')
menu.hide()
print('SCALING_PASS')
'''
        env = {**os.environ, 'QT_SCALE_FACTOR': '2', 'QT_QPA_PLATFORM': 'offscreen'}
        result = subprocess.run(['/usr/bin/python3','-B','-c',code], cwd=ROOT, env=env,
                                capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr+result.stdout)
        self.assertIn('SCALING_PASS',result.stdout)


    def test_live_display_scale_change_preserves_review_and_cancel_selection(self):
        code = r'''
import importlib.util,os,json
from pathlib import Path
from unittest import mock
spec=importlib.util.spec_from_file_location('live_scale_overlay',Path('src/session-overlay.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.xproperty=mock.Mock()
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
menu=m.Overlay();menu.resize(1920,1200);menu.show();app.processEvents()
menu.planner=mock.Mock();menu.planner.busy=False
menu.request=mock.Mock();menu.request.busy=False
menu.choose(1)
plan={'path':'/tmp/hstn-synthetic-review','apps':[{'label':'Synthetic game','processes':[{'name':'fixture.exe'}]}],'warnings':[]}
menu.plan_finished(0,json.dumps(plan));app.processEvents()
assert menu.mode=='confirm' and menu.selection==1
before=menu.panel.size()
menu.set_render_scale(1.6818664073944092);app.processEvents()
assert menu.panel.width()>before.width() and menu.panel.height()>before.height()
assert menu.panel.width()<menu.width() and menu.panel.height()<menu.height()
assert menu.mode=='confirm' and menu.selection==1 and menu.plan_path==plan['path']
assert menu.buttons[0].text()=='Close and switch' and menu.buttons[1].text()=='Cancel'
menu.hide_overlay()
print('LIVE_SCALE_PASS')
'''
        result = subprocess.run(['/usr/bin/python3','-B','-c',code], cwd=ROOT,
                                capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr+result.stdout)
        self.assertIn('LIVE_SCALE_PASS',result.stdout)
