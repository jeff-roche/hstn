import importlib.util
import json
import os
import socket
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
    def test_service_readiness_notifies_only_the_configured_socket(self):
        overlay=load('notify_overlay',ROOT/'src/session-overlay.py')
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'notify.sock')
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as server:
                server.bind(path);server.settimeout(1)
                with mock.patch.dict(os.environ, {'NOTIFY_SOCKET':path}):
                    overlay.notify_ready()
                self.assertEqual(server.recv(128),b'READY=1')
        with mock.patch.dict(os.environ,{},clear=True),mock.patch.object(overlay.socket,'socket') as connect:
            overlay.notify_ready()
            connect.assert_not_called()

    def test_desktop_switch_preserves_session_environment(self):
        overlay = load('desktop_switch_overlay', ROOT/'src/session-overlay.py')
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
spec=importlib.util.spec_from_file_location('overlay',Path('src/session-overlay.py').resolve())
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
assert menu.selection==2 and menu.buttons[2].text()=='Return to Desktop'
app.sendEvent(menu.buttons[0],m.QtCore.QEvent(m.QtCore.QEvent.Enter))
assert menu.selection==2
menu.keyPressEvent(m.QtGui.QKeyEvent(m.QtCore.QEvent.KeyPress,m.QtCore.Qt.Key_Return,m.QtCore.Qt.NoModifier))
assert not menu.isVisible()
menu.planner.start.assert_not_called()
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

    def test_native_background_identity_matches_autostart_instead_of_open_shortcut(self):
        code = r'''
import importlib.util,os
from pathlib import Path
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,Path(path).resolve())
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
m=load('identity_overlay','src/session-overlay.py')
integration=load('identity_integration','scripts/desktop-integration.py')
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.create_application(True)
assert app.testAttribute(m.QtCore.Qt.AA_DisableSessionManager)
files=integration.install_files(Path.cwd(),Path('/home/fixture'),Path('/home/fixture/data'),Path('/home/fixture/config'),Path('/home/fixture/Desktop'))
assert Path('/home/fixture/config/autostart')/(app.desktopFileName()+'.desktop') in files
entry=files[Path('/home/fixture/data/applications')/(app.desktopFileName()+'.desktop')][0]
assert 'NoDisplay=true' in entry and '"autostart"' in entry
assert app.desktopFileName()!='hstn-open'
assert not app.topLevelWindows()
print('BACKGROUND_IDENTITY_PASS')
'''
        result = subprocess.run(['/usr/bin/python3','-B','-c',code],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('BACKGROUND_IDENTITY_PASS',result.stdout)

    def test_baseline_reset_discards_native_select_without_blocking_controller_accept(self):
        code = r'''
import importlib.util,os,time
from pathlib import Path
from unittest import mock
spec=importlib.util.spec_from_file_location('reset_overlay',Path('src/session-overlay.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
lease=object.__new__(m.DesktopMapLease)
lease.native_input_after=0
lease.request=mock.Mock(return_value={'ok':True,'repaired':True})
menu=m.Overlay(desktop=True)
menu.planner=mock.Mock();menu.planner.busy=False
menu.request=mock.Mock();menu.request.busy=False
router=mock.Mock();router.verify_capture.side_effect=lambda native=False:lease.check(native=native)
menu.router=router
menu.show();app.processEvents()
# Steam's B can have become a native select while DeckyPlumber restored Default.
menu.choose(1)
assert not menu.isVisible()
menu.planner.start.assert_not_called();menu.request.start.assert_not_called()
menu.buttons[0].click()  # A queued native click after dismissal is inert.
menu.planner.start.assert_not_called()
# A queued native click is still refused after the background timer repaired it.
menu.show();lease.request.return_value={'ok':True,'repaired':False}
menu.choose(0)
assert not menu.isVisible();menu.planner.start.assert_not_called()
# A DBus Accept is unambiguous and works immediately with the repaired mapping.
menu.show();lease.request.return_value={'ok':True,'repaired':True}
menu.controller('ui_accept')
menu.planner.start.assert_called_once_with('steam',arguments=['plan','steam'])
menu.hide_overlay();menu.planner.start.reset_mock()
# Once settled, intentional keyboard/mouse selection remains available.
lease.native_input_after=time.monotonic()-1
lease.request.return_value={'ok':True,'repaired':False}
menu.show();menu.choose(1)
menu.planner.start.assert_called_once_with('heroic',arguments=['plan','heroic'])
menu.hide_overlay()
print('BASELINE_RESET_PASS')
'''
        result=subprocess.run(['/usr/bin/python3','-B','-c',code],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertIn('BASELINE_RESET_PASS',result.stdout)

    def test_unknown_profile_change_refuses_confirmation_and_preserves_running_apps(self):
        code = r'''
import importlib.util,os,json
from pathlib import Path
from unittest import mock
spec=importlib.util.spec_from_file_location('confirm_reset_overlay',Path('src/session-overlay.py').resolve())
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
os.environ['QT_QPA_PLATFORM']='offscreen'
app=m.QtWidgets.QApplication([])
menu=m.Overlay(desktop=True)
menu.planner=mock.Mock();menu.planner.busy=False
menu.request=mock.Mock();menu.request.busy=False
menu.closer=mock.Mock()
menu.choose(0)
menu.plan_finished(0,json.dumps({'path':'/tmp/hstn-synthetic-review','apps':[{'label':'Fixture','processes':[{'name':'fixture.exe'}]}],'warnings':[]}))
router=mock.Mock();router.verify_capture.side_effect=RuntimeError('External profile edit')
menu.router=router;menu.show();app.processEvents()
menu.choose(0,from_controller=True)
assert not menu.isVisible()
menu.closer.start.assert_not_called();menu.request.start.assert_not_called()
print('PROFILE_REFUSAL_PASS')
'''
        result=subprocess.run(['/usr/bin/python3','-B','-c',code],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        self.assertIn('PROFILE_REFUSAL_PASS',result.stdout)

    def test_kwin_focus_native_window_lifecycle(self):
        # Execute the actual JS against a workspace fixture, including vanished windows.
        script = (ROOT/'templates/config/kwin/hstn-focus.js').read_text().replace('__HSTN_PID__','123').replace('__HSTN_TITLE__',json.dumps('HSTN — Session menu'))
        harness = r'''
function signal(){let handlers=[];return {connect:f=>handlers.push(f),emit:(...a)=>handlers.forEach(f=>f(...a))};}
let previous={pid:9,caption:'Native Wayland app',deleted:false};
let other={pid:8,caption:'Other app',deleted:false};
let windows=[previous,other];
let KWin={PlacementArea:0};
let workspace={activeWindow:previous,windowAdded:signal(),windowActivated:signal(),windowList:()=>windows,clientArea:()=>({x:0,y:0,width:1011,height:600})};
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
let toast={pid:123,caption:'HSTN — Controller notification',windowShown:signal(),frameGeometry:{x:0,y:0,width:360,height:76}};
workspace.windowAdded.emit(toast);
if(workspace.activeWindow!==previous)throw Error('Notification stole focus');
if(toast.frameGeometry.x!==627||toast.frameGeometry.y!==500||toast.opacity!==0.8||!toast.keepAbove)throw Error('Native notification position/opacity');
'''
        runner = 'from PySide6.QtCore import QCoreApplication\nfrom PySide6.QtQml import QJSEngine\nimport sys\napp=QCoreApplication([])\nresult=QJSEngine().evaluate(sys.stdin.read())\nif result.isError():\n print(result.toString());sys.exit(1)\n'
        result=subprocess.run(['/usr/bin/python3','-B','-c',runner],input=harness+script+checks,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_desktop_capture_checks_existing_steam_routes(self):
        overlay=load('desktop_route_overlay', ROOT/'src/session-overlay.py')
        app=overlay.QtCore.QCoreApplication.instance() or overlay.QtCore.QCoreApplication([])
        with mock.patch.dict(os.environ, {'SESSION_SWITCH_DESKTOP_MODE':'1'}):
            router=overlay.InputRouter()
            router.state['modes']={'/controller':0}
            with mock.patch.object(overlay,'desktop_isolation_issues',return_value=['Steam already holds physical source']) as inspect, mock.patch.object(overlay,'set_property') as mutate:
                with self.assertRaisesRegex(RuntimeError,'Steam already holds'):router.capture(True)
                inspect.assert_called_once();mutate.assert_not_called()

    def test_desktop_single_output_preflight_accepts_suppressed_siblings(self):
        overlay=load('desktop_single_output_check',ROOT/'src/session-overlay.py')
        with mock.patch.dict(os.environ,{'SESSION_SWITCH_INPUT_TARGET':'ds5-single'}),mock.patch.object(overlay.subprocess,'run',return_value=mock.Mock(returncode=0,stdout='{"isolation_issues":[]}')) as run:
            self.assertEqual(overlay.desktop_isolation_issues(),[])
            self.assertIn('--single-playstation',run.call_args.args[0])

    def test_desktop_isolation_timeout_still_refuses_capture(self):
        overlay=load('desktop_timeout_check',ROOT/'src/session-overlay.py')
        with mock.patch.object(overlay.subprocess,'run',side_effect=subprocess.TimeoutExpired('probe',10)):
            issues=overlay.desktop_isolation_issues()
        self.assertEqual(len(issues),1)
        self.assertIn('Could not verify Desktop input isolation',issues[0])

    def test_release_failure_on_one_controller_does_not_strand_others(self):
        overlay=load('desktop_release_overlay', ROOT/'src/session-overlay.py')
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
