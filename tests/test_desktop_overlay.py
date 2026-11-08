import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class DesktopOverlayTest(unittest.TestCase):
    def test_desktop_switch_preserves_session_environment(self):
        overlay = load('desktop_switch_overlay', ROOT/'prototypes/session-overlay.py')
        with mock.patch.dict(os.environ, {'SESSION_SWITCH_DESKTOP_MODE':'1', 'XDG_CURRENT_DESKTOP':'KDE', 'XDG_SESSION_TYPE':'wayland', 'WAYLAND_DISPLAY':'wayland-1'}):
            args = overlay.switch_command('/tmp/helper', 'steam')
        self.assertIn('--setenv=XDG_CURRENT_DESKTOP=KDE', args)
        self.assertIn('--setenv=WAYLAND_DISPLAY=wayland-1', args)
        self.assertIn('--setenv=XDG_SESSION_TYPE=wayland', args)

    def test_lease_excludes_second_owner_until_watchdog_exits(self):
        support = load('desktop_support_lease', ROOT/'scripts/desktop-overlay-support.py')
        with tempfile.TemporaryDirectory() as folder:
            first = support.OverlayLease(Path(folder))
            with self.assertRaises(RuntimeError): support.OverlayLease(Path(folder))
            child = subprocess.Popen(['/usr/bin/python3', '-c', 'import sys;sys.stdin.read()'],
                                     stdin=subprocess.PIPE, pass_fds=(first.fileno(),))
            first.close()
            try:
                with self.assertRaises(RuntimeError): support.OverlayLease(Path(folder))
            finally:
                child.communicate(timeout=3)
            second = support.OverlayLease(Path(folder)); second.close()

    def test_desktop_menu_noop_and_guard_fallback(self):
        code = r'''
import importlib.util,os
from pathlib import Path
from unittest import mock
spec=importlib.util.spec_from_file_location('overlay',Path('prototypes/session-overlay.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
menu=m.Overlay(desktop=True)
menu.planner=mock.Mock();menu.planner.busy=False
menu.choose(2);menu.planner.start.assert_not_called()
assert menu.buttons[3].text()=='Return to Desktop'
menu.reset_menu();assert menu.buttons[3].text()=='Return to Desktop'
router=mock.Mock();menu.router=router
menu.disable_controller('guard stopped')
router.close.assert_called_once();assert menu.router is None
menu.open_overlay();assert menu.isVisible()
assert 'guard stopped' in menu.status.text()
menu.hide_overlay()
# Recovery must finish even when the controller disappeared during release.
router=mock.Mock();menu.router=router
router.capture.side_effect=RuntimeError('controller gone')
menu.show();menu.disable_controller('guard stopped')
router.close.assert_called_once();assert menu.router is None
menu.open_overlay();assert menu.isVisible()
menu.disable_controller('queued guard stopped');assert menu.isVisible()
menu.hide_overlay()
print('DESKTOP_MENU_PASS')
'''
        result = subprocess.run(['/usr/bin/python3', '-B', '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DESKTOP_MENU_PASS', result.stdout)

    def test_kwin_focus_native_window_lifecycle(self):
        # Execute the actual JS against a workspace fixture, including vanished windows.
        script = (ROOT/'templates/config/kwin/hstn-focus.js').read_text().replace('__HSTN_PID__','123').replace('__HSTN_TITLE__',json.dumps('HSTN — Session menu'))
        harness = r'''
function signal(){let handlers=[];return {connect:f=>handlers.push(f),emit:(...a)=>handlers.forEach(f=>f(...a))};}
let previous={pid:9,caption:'Native Wayland app',deleted:false};
let other={pid:8,caption:'Other app',deleted:false};
let windows=[previous,other];
let workspace={activeWindow:previous,windowAdded:signal(),windowActivated:signal(),windowList:()=>windows};
'''
        checks = r'''
let menu={pid:123,caption:'HSTN — Session menu',windowShown:signal(),windowHidden:signal(),closed:signal()};
windows.push(menu);workspace.windowAdded.emit(menu);
if(workspace.activeWindow!==menu)throw Error('Menu did not activate');
menu.windowHidden.emit();if(workspace.activeWindow!==previous)throw Error('Native app not restored');
workspace.activeWindow=other;workspace.windowActivated.emit(other);
menu.windowShown.emit();if(workspace.activeWindow!==menu)throw Error('Reopen failed');
windows=windows.filter(w=>w!==other);workspace.activeWindow=previous;
menu.windowHidden.emit();if(workspace.activeWindow!==previous)throw Error('Missing previous app changed focus');
workspace.activeWindow=previous;workspace.windowActivated.emit(previous);
let foreign={pid:124,caption:'HSTN — Session menu'};workspace.windowAdded.emit(foreign);
if(workspace.activeWindow!==previous)throw Error('Activated foreign window');
'''
        runner = 'from PySide6.QtCore import QCoreApplication\nfrom PySide6.QtQml import QJSEngine\nimport sys\napp=QCoreApplication([])\nresult=QJSEngine().evaluate(sys.stdin.read())\nif result.isError():\n print(result.toString());sys.exit(1)\n'
        result=subprocess.run(['/usr/bin/python3','-B','-c',runner],input=harness+script+checks,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_desktop_capture_checks_existing_steam_routes(self):
        overlay=load('desktop_route_overlay', ROOT/'prototypes/session-overlay.py')
        app=overlay.QtCore.QCoreApplication.instance() or overlay.QtCore.QCoreApplication([])
        with mock.patch.dict(os.environ, {'SESSION_SWITCH_DESKTOP_MODE':'1'}):
            router=overlay.InputRouter()
            router.state['modes']={'/controller':0}
            with mock.patch.object(overlay,'desktop_isolation_issues',return_value=['Steam already holds physical source']) as inspect, mock.patch.object(overlay,'set_property') as mutate:
                with self.assertRaisesRegex(RuntimeError,'Steam already holds'):router.capture(True)
                inspect.assert_called_once();mutate.assert_not_called()

    def test_desktop_single_output_preflight_accepts_suppressed_siblings(self):
        overlay=load('desktop_single_output_check',ROOT/'prototypes/session-overlay.py')
        with mock.patch.dict(os.environ,{'SESSION_SWITCH_INPUT_TARGET':'ds5-single'}),mock.patch.object(overlay.subprocess,'run',return_value=mock.Mock(returncode=0,stdout='{"isolation_issues":[]}')) as run:
            self.assertEqual(overlay.desktop_isolation_issues(),[])
            self.assertIn('--single-playstation',run.call_args.args[0])

    def test_release_failure_on_one_controller_does_not_strand_others(self):
        overlay=load('desktop_release_overlay', ROOT/'prototypes/session-overlay.py')
        self.app=overlay.QtCore.QCoreApplication.instance() or overlay.QtCore.QCoreApplication([])
        router=overlay.InputRouter();router.state['modes']={'/gone':0,'/present':0}
        with mock.patch.object(overlay,'set_property',side_effect=[RuntimeError('gone'),None]) as mutate:
            router.capture(False)
            self.assertEqual(mutate.call_count,2)

    def test_desktop_dbus_repeated_open_and_status(self):
        code=r'''
import importlib.util,json,os
from pathlib import Path
from unittest import mock
from PySide6 import QtCore,QtDBus
spec=importlib.util.spec_from_file_location('support',Path('scripts/desktop-overlay-support.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
app=QtCore.QCoreApplication([])
class Menu(QtCore.QObject):
 def __init__(self):super().__init__();self.router=None;self.visible=False
 def open_overlay(self):self.visible=True
 def hide_overlay(self):self.visible=False
 def isVisible(self):return self.visible
menu=Menu();endpoint=m.DesktopEndpoint(menu)
iface=QtDBus.QDBusInterface(m.SERVICE,m.OBJECT,m.INTERFACE,QtDBus.QDBusConnection.sessionBus())
for method in ('Open','Open'):
 reply=iface.call(method);assert reply.type()!=QtDBus.QDBusMessage.ErrorMessage,reply.errorMessage()
assert json.loads(iface.call('Status').arguments()[0])['visible']
assert not json.loads(iface.call('Status').arguments()[0])['controller']
iface.call('Hide');assert not menu.visible
endpoint.close()
'''
        result=subprocess.run(['dbus-run-session','--','/usr/bin/python3','-B','-c',code],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
