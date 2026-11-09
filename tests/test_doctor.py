import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('doctor', ROOT/'scripts/doctor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DoctorTests(unittest.TestCase):
    def test_xdg_user_units_and_native_guard_paths(self):
        m = load()
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            native = base/'native'
            native.mkdir()
            (native/'PACKAGE-MANAGED').write_text('package')
            paths = []
            def inspect(path, **kwargs):
                paths.append(Path(path))
                return 'PASS', str(path)
            with patch.object(m, 'ROOT', native), patch.dict(m.os.environ, {'XDG_CONFIG_HOME': str(base/'config')}), \
                 patch.object(m, 'file_check', side_effect=inspect), patch.object(m, 'probe', return_value=(0, 'active')), \
                 patch.object(m, 'in_gamescope', return_value=False):
                m.collect()
            self.assertIn(base/'config/systemd/user/session-switch-overlay.service', paths)
            self.assertIn(Path('/usr/libexec/session-switch-input-guard.py'), paths)
            self.assertNotIn(Path('/usr/local/libexec/session-switch-input-guard.py'), paths)
    def test_desktop_skips_live_isolation_even_with_stale_runtime_file(self):
        m = load()
        with patch.dict(m.os.environ, {'XDG_CURRENT_DESKTOP': 'KDE'}, clear=True):
            self.assertFalse(m.in_gamescope())
        with patch.dict(m.os.environ, {'XDG_CURRENT_DESKTOP': 'gamescope'}, clear=True):
            self.assertTrue(m.in_gamescope())

    def test_gamescope_runtime_checks_only_appear_inside_gamescope(self):
        m = load()
        for gaming in (False, True):
            with self.subTest(gamescope=gaming), patch.object(m, 'in_gamescope', return_value=gaming), \
                 patch.object(m, 'probe', return_value=(0, 'active')), \
                 patch.object(m, 'routing_check', return_value=('PASS', 'ready')) as routing:
                checks = m.collect()
            names = {check['name'] for check in checks}
            self.assertEqual('overlay:state' in names, gaming)
            self.assertEqual('controller:isolation' in names, gaming)
            self.assertFalse(any(check['status'] == 'SKIP' for check in checks))
            self.assertEqual(routing.call_count, int(gaming))

    def test_desktop_output_does_not_show_zero_skips(self):
        m = load()
        with patch.object(m, 'collect', return_value=[{'name': 'check', 'status': 'PASS', 'detail': 'ready'}]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(m.main([]), 0)
        self.assertNotIn('skip', output.getvalue().lower())

    def test_default_output_shows_only_warning_and_failure_details(self):
        m = load()
        checks = [{'name': status.lower() + '_check', 'status': status, 'detail': status + ' detail'}
                  for status in ('PASS', 'WARN', 'FAIL', 'SKIP')]
        for options in ([], ['-v'], ['--verbose']):
            with self.subTest(options=options), patch.object(m, 'collect', return_value=checks), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(m.main(options), 1)
            text = output.getvalue()
            self.assertIn('[WARN] warn_check', text)
            self.assertIn('[FAIL] fail_check', text)
            self.assertEqual('[PASS] pass_check' in text, bool(options))
            self.assertEqual('[SKIP] skip_check' in text, bool(options))

    def test_json_keeps_all_checks_without_verbose(self):
        m = load()
        checks = [{'name': 'passed', 'status': 'PASS', 'detail': 'ready'},
                  {'name': 'warning', 'status': 'WARN', 'detail': 'inspect'}]
        with patch.object(m, 'collect', return_value=checks), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(m.main(['--json']), 0)
        self.assertEqual(json.loads(output.getvalue())['checks'], checks)

    def test_sddm_override_precedence_and_comma_directories(self):
        m = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root/'usr/lib/sddm/sddm.conf.d'; vendor.mkdir(parents=True)
            local = root/'etc/sddm.conf.d'; local.mkdir(parents=True)
            (vendor/'10-session.conf').write_text('[Wayland]\nSessionDir=/wrong\n')
            (local/'20-session.conf').write_text('[Wayland]\nSessionDir=/etc/wayland-sessions,/usr/share/wayland-sessions\n')
            self.assertEqual(m.session_dirs(root), ['/etc/wayland-sessions', '/usr/share/wayland-sessions'])
            (root/'etc/sddm.conf').write_text('[Wayland]\nSessionDir=/final\n')
            self.assertEqual(m.session_dirs(root), ['/final'])

    def test_broken_link_and_writable_root_helper_fail(self):
        m = load()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'helper'; path.symlink_to('/nonexistent/hstn-doctor-test')
            self.assertEqual(m.file_check(path)[0], 'FAIL')
            path.unlink(); path.write_text('hello'); path.chmod(0o666)
            self.assertEqual(m.file_check(path, trusted=True)[0], 'FAIL')

    def test_probe_timeout_is_bounded_and_reports_failure(self):
        m = load()
        with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired('systemctl', 5)) as run:
            code, output = m.probe(['systemctl', 'is-active', 'inputplumber.service'])
            self.assertNotEqual(code, 0)
            self.assertIn('timed out', output)
            self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_reports_failures_in_json_and_nonzero_exit(self):
        m = load()
        checks = [{'name':'guard', 'status':'FAIL', 'detail':'missing'},
                  {'name':'routes', 'status':'SKIP', 'detail':'Desktop'}]
        with patch.object(m, 'collect', return_value=checks), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(m.main(['--json']), 1)
        report = json.loads(out.getvalue())
        self.assertEqual(report['summary']['FAIL'], 1)
        self.assertFalse(report['ok'])

    def test_warnings_and_skips_are_not_failures(self):
        m = load()
        with patch.object(m, 'collect', return_value=[{'name':'routes','status':'SKIP','detail':'Desktop'},
                                                     {'name':'inspection','status':'WARN','detail':'incomplete'}]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main([]), 0)

    def test_collector_only_invokes_read_only_command_families(self):
        m = load()
        commands = []
        def probe(command, timeout=5):
            commands.append(command)
            if command[:2] == ['systemctl', '--user']:
                return 0, 'inactive'
            if command[0] == 'busctl':
                return 0, 'SetTemporarySession'
            if command[:2] == ['flatpak', 'override']:
                return 0, '[Session Bus Policy]\norg.freedesktop.Flatpak=talk\n'
            return 0, 'active'
        with patch.object(m, 'probe', side_effect=probe), patch.object(m, 'in_gamescope', return_value=False):
            report = m.collect()
        self.assertTrue(report)
        self.assertFalse(any(c[0] in ('sudo', 'systemd-run', 'steamosctl') for c in commands))
        self.assertFalse(any(action in c for c in commands for action in ('start','stop','restart','enable','set-property','call')))

    def test_heroic_terminal_uses_single_playstation_check_without_private_env(self):
        m = load()
        with patch.dict(m.os.environ, {}, clear=True), patch.object(m, 'probe', return_value=(0, 'active')):
            self.assertEqual(m.input_target(), 'ds5-single')

    def test_route_failure_and_unavailable_inspection_are_distinct(self):
        m = load()
        with patch.object(m, 'input_target', return_value='native'):
            with patch.object(m, 'probe', return_value=(124, 'timed out')):
                self.assertEqual(m.routing_check()[0], 'WARN')
            with patch.object(m, 'probe', return_value=(0, '{"issues":["Physical source remains readable"],"gaps":[]}')):
                self.assertEqual(m.routing_check()[0], 'FAIL')
            with patch.object(m, 'probe', return_value=(0, '{"issues":[],"gaps":["permission denied"]}')):
                self.assertEqual(m.routing_check()[0], 'WARN')

    def test_helper_import_does_not_write_bytecode(self):
        m = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'scripts').mkdir()
            (root/'scripts/probe.py').write_text('value = 42\n')
            with patch.object(m, 'ROOT', root):
                self.assertEqual(m.load('probe').value, 42)
            self.assertFalse((root/'scripts/__pycache__').exists())

    def test_effective_permissions_reject_denial_despite_other_scope_grants(self):
        m = load()
        with patch.object(m, 'probe', return_value=(0, '[Session Bus Policy]\norg.freedesktop.Flatpak=none\n')) as run:
            self.assertEqual(m.permission_check()[0], 'FAIL')
            self.assertEqual(run.call_args.args[0], ['flatpak','info','--show-permissions','com.heroicgameslauncher.hgl'])

    def test_effective_permission_grant_and_inspection_failure(self):
        m = load()
        with patch.object(m, 'probe', return_value=(0, '[Session Bus Policy]\norg.freedesktop.Flatpak=talk\n')):
            self.assertEqual(m.permission_check()[0], 'PASS')
        with patch.object(m, 'probe', return_value=(1, 'ambiguous installation')):
            self.assertEqual(m.permission_check()[0], 'WARN')

    def test_session_entry_requires_actual_executable_and_exact_target(self):
        m = load()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.desktop'
            with patch.object(m, 'session_dirs', return_value=[directory]):
                for command in ('/bin/echo gamescope-session-plus ogui-steam',
                                'gamescope-session-plus ogui-steam-broken',
                                'gamescope-session-plus ogui-steam extra'):
                    path.write_text('[Desktop Entry]\nType=Application\nExec='+command+'\n')
                    self.assertEqual(m.desktop_entry_check('test.desktop')[0], 'FAIL')
                path.write_text('[Desktop Entry]\nType=Application\nExec=/usr/bin/gamescope-session-plus ogui-steam\n')
                self.assertEqual(m.desktop_entry_check('test.desktop')[0], 'PASS')
