import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]

def module():
    spec=importlib.util.spec_from_file_location('desktop_integration',ROOT/'scripts/desktop-integration.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class DesktopIntegrationTest(unittest.TestCase):
    def test_three_icons_and_escaped_paths(self):
        m=module()
        with tempfile.TemporaryDirectory(prefix='hstn space % ') as folder:
            home=Path(folder)
            files=m.install_files(ROOT,home,home/'data',home/'config',home/'Desk top')
            desktop=[(p,v) for p,v in files.items() if p.parent==home/'Desk top']
            self.assertEqual(len(desktop),3)
            for path,(content,mode) in desktop:
                self.assertIn('Type=Application',content)
                self.assertEqual(mode,0o755)
            open_entry=files[home/'data/applications/hstn-open.desktop'][0]
            self.assertIn('Icon='+str(ROOT/'assets/logo/hstn-rocket-256.png'),open_entry)
            self.assertIn('StartupWMClass=hstn-overlay',open_entry)
            installed=m.install_files(ROOT,home,home/'data',home/'config',home/'Desk top',runtime_root=home/'runtime')
            self.assertIn('Icon='+str(home/'runtime/assets/logo/hstn-rocket-256.png'),installed[home/'data/applications/hstn-open.desktop'][0])
            quoted=m.exec_arg('/a space/"$`\\%file')
            self.assertIn('%%',quoted)
            self.assertIn('\\\\$',quoted)
            self.assertIn('\\\\\\\\',quoted)
            unit=files[home/'config/systemd/user/hstn-desktop-overlay.service'][0]
            self.assertIn('PartOf=graphical-session.target',unit)
            self.assertIn('SESSION_SWITCH_INPUT_TARGET=ds5-single',unit)
            self.assertNotIn('@ROOT@',unit)

    def test_install_repeat_remove_preserves_original_and_user_edits(self):
        m=module()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'state/install.json';icon=root/'Desktop/icon.desktop'
            icon.parent.mkdir();icon.write_text('original');icon.chmod(0o640)
            other=root/'Desktop/other';other.write_text('untouched')
            files={icon:('installed',0o755)}
            m.apply_files(files,state);m.apply_files(files,state)
            self.assertEqual(icon.read_text(),'installed')
            self.assertEqual(m.remove_files(state),[])
            self.assertEqual(icon.read_text(),'original');self.assertEqual(icon.stat().st_mode&0o777,0o640)
            m.apply_files(files,state);icon.write_text('my edit')
            self.assertEqual(m.remove_files(state),[str(icon)])
            self.assertEqual(icon.read_text(),'my edit');self.assertEqual(other.read_text(),'untouched')

    def test_install_preserves_later_edits_and_symlink_collision(self):
        m=module()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'state/install.json';icon=root/'icon';target=root/'target';target.write_text('original')
            icon.symlink_to(target)
            m.apply_files({icon:('installed',0o755)},state)
            self.assertFalse(icon.is_symlink());self.assertEqual(target.read_text(),'original')
            m.remove_files(state);self.assertTrue(icon.is_symlink())
            m.apply_files({icon:('installed',0o755)},state);icon.write_text('edited')
            with self.assertRaises(RuntimeError):m.apply_files({icon:('upgraded',0o755)},state)
            self.assertEqual(icon.read_text(),'edited')

    def test_session_environment_is_separate_and_requires_kde(self):
        m=module()
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder);gamescope=runtime/'session-switch-overlay.env';gamescope.write_text('original')
            env={'XDG_CURRENT_DESKTOP':'KDE','DISPLAY':':1','XAUTHORITY':'/a path/xauth','WAYLAND_DISPLAY':'wayland-1','XDG_SESSION_TYPE':'wayland'}
            path=m.write_session_environment(runtime,env)
            self.assertIn('DISPLAY=":1"',path.read_text());self.assertEqual(gamescope.read_text(),'original')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(RuntimeError):m.write_session_environment(runtime,{'XDG_CURRENT_DESKTOP':'gamescope','DISPLAY':':2'})

    def test_startup_resolves_current_kde_display_instead_of_old_terminal(self):
        m=module()
        with tempfile.TemporaryDirectory() as folder:
            proc=Path(folder);process=proc/'42';process.mkdir()
            (process/'comm').write_text('plasmashell\n')
            (process/'environ').write_bytes(b'DISPLAY=:2\0XAUTHORITY=/current/auth\0XDG_CURRENT_DESKTOP=KDE\0XDG_SESSION_ID=7\0PRIVATE_TOKEN=never-import\0')
            stale={'DISPLAY':':0','XAUTHORITY':'/stale/auth','XDG_SESSION_ID':'3','XDG_RUNTIME_DIR':'/run/user/test'}
            reply=mock.Mock(stdout=json.dumps({'type':'u','data':[42]}))
            with mock.patch.object(m,'run',return_value=reply):
                result=m.desktop_environment(stale,proc)
            self.assertEqual(result['DISPLAY'],':2');self.assertEqual(result['XAUTHORITY'],'/current/auth')
            self.assertEqual(result['XDG_SESSION_ID'],'7');self.assertEqual(result['XDG_RUNTIME_DIR'],'/run/user/test')
            self.assertNotIn('PRIVATE_TOKEN',result)
            (process/'comm').write_text('some-other-app\n')
            with mock.patch.object(m,'run',return_value=reply):
                with self.assertRaises(RuntimeError):m.desktop_environment(stale,proc)

    def test_startup_does_not_replace_environment_if_live_session_lookup_fails(self):
        m=module()
        with mock.patch.object(m,'gamescope_active',return_value=False),mock.patch.object(m,'desktop_environment',side_effect=RuntimeError('no current KDE')),mock.patch.object(m,'write_session_environment') as write:
            with self.assertRaises(RuntimeError):m.start_desktop()
            write.assert_not_called()

    def test_autostart_refuses_active_gamescope_before_mutation(self):
        m=module()
        with mock.patch.object(m,'gamescope_active',return_value=True),mock.patch.object(m,'write_session_environment') as write:
            with self.assertRaises(RuntimeError):m.start_desktop()
            write.assert_not_called()

    def test_open_has_bounded_startup_and_does_not_write_stale_environment(self):
        m=module()
        with mock.patch.object(m,'ipc',side_effect=[RuntimeError('not ready'),RuntimeError('still not ready')]),mock.patch.object(m,'run') as run,mock.patch.object(m,'gamescope_active',return_value=False):
            with self.assertRaises(RuntimeError):m.open_menu()
            self.assertTrue(run.called)
            self.assertIn('start',run.call_args.args[0])

    def test_open_never_starts_desktop_over_active_gamescope(self):
        m=module()
        with mock.patch.object(m,'ipc',side_effect=RuntimeError('not ready')),mock.patch.object(m,'gamescope_active',return_value=True),mock.patch.object(m,'run') as run:
            with self.assertRaises(RuntimeError):m.open_menu()
            run.assert_not_called()

    def test_failed_upgrade_restores_original_and_can_retry(self):
        m=module()
        for action in ('remove','retry'):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);state=root/'record';icon=root/'icon';icon.write_text('original')
                m.apply_files({icon:('v1',0o755)},state)
                original_write=m.atomic_bytes
                def fail_file(path,data,mode):
                    if path==icon:raise OSError('disk full')
                    return original_write(path,data,mode)
                with mock.patch.object(m,'atomic_bytes',side_effect=fail_file):
                    with self.assertRaises(OSError):m.apply_files({icon:('v2',0o755)},state)
                self.assertEqual(icon.read_text(),'v1')
                if action=='retry':
                    m.apply_files({icon:('v2',0o755)},state)
                    self.assertEqual(icon.read_text(),'v2')
                self.assertEqual(m.remove_files(state),[])
                self.assertEqual(icon.read_text(),'original')

if __name__=='__main__':unittest.main()
