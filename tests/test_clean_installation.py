import importlib.util
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/('installer' if name in ('install-hstn', 'install-system', 'install-state', 'clean-installation', 'remove-launcher-assets') else 'scripts')/f'{name}.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class CleanInstallationTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'installer/clean-installation.py').is_file(), 'clean-slate removal is missing')
        self.m = load('clean-installation'); self.installer = load('install-hstn')
        self.tmp = tempfile.TemporaryDirectory(prefix='hstn clean space ')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.locations = self.installer.Locations(self.home, {}, self.home/'Desktop')

    def test_legacy_cleanup_removes_known_wrappers_backups_and_private_diagnostics(self):
        command = self.locations.bin/'switch-to-steam'
        command.parent.mkdir(parents=True)
        command.write_bytes((ROOT/'scripts/switch-to-steam').read_bytes())
        backup = command.with_name(command.name + '.bak-hstn-20261107'); backup.write_bytes((ROOT/'scripts/switch-to-steam').read_bytes())
        other = command.with_name('my-other-command'); other.write_bytes(b'keep')
        logs = self.locations.state.parent.parent/'session-switch/diagnostics/report.json'
        logs.parent.mkdir(parents=True); logs.write_text('private test capture')
        template = self.m.templates(ROOT, self.installer.LINKS)
        plan = self.m.user_files(self.locations, template, legacy=True)
        self.m.apply_files(plan, self.locations)
        self.m.finish(self.locations)
        self.assertFalse(command.exists()); self.assertFalse(backup.exists()); self.assertFalse(logs.exists())
        self.assertEqual(other.read_bytes(), b'keep')
        self.assertFalse((self.locations.state.parent.parent/'session-switch').exists())

    def test_unknown_legacy_command_is_a_conflict_before_deletion(self):
        command = self.locations.bin/'switch-to-steam'
        command.parent.mkdir(parents=True); command.write_text('my unrelated command')
        with self.assertRaisesRegex(RuntimeError, 'unrecognized|edited'):
            self.m.user_files(self.locations, self.m.templates(ROOT, self.installer.LINKS), legacy=True)
        self.assertEqual(command.read_text(), 'my unrelated command')

    def test_session_runtime_cleanup_removes_only_hstn_artifacts(self):
        runtime = self.home/'run'; runtime.mkdir()
        locations = self.installer.Locations(self.home, {'XDG_RUNTIME_DIR': str(runtime)}, self.home/'Desktop')
        owned = runtime/'hstn-desktop-overlay.env'; owned.write_text('DISPLAY=:1\n')
        other = runtime/'other-app.env'; other.write_text('keep')
        plan = self.m.user_files(locations, self.m.templates(ROOT, self.installer.LINKS))
        self.m.apply_files(plan, locations)
        self.m.finish(locations)
        self.assertFalse(owned.exists()); self.assertEqual(other.read_text(), 'keep')

    def test_unrecognized_backup_is_preserved(self):
        backup = self.locations.bin/'switch-to-steam.bak'
        backup.parent.mkdir(parents=True); backup.write_bytes(b'unrelated backup')
        with self.assertRaisesRegex(RuntimeError, 'unrecognized|edited'):
            self.m.user_files(self.locations, self.m.templates(ROOT, self.installer.LINKS), legacy=True)
        self.assertEqual(backup.read_bytes(), b'unrelated backup')

    def test_pre_desktop_gamescope_unit_is_recognized_without_losing_custom_units(self):
        unit = self.locations.config/'systemd/user/session-switch-overlay.service'
        unit.parent.mkdir(parents=True)
        content = (ROOT/'templates/systemd/session-switch-overlay.service').read_bytes().replace(
            b'Conflicts=hstn-desktop-overlay.service\n', b'').replace(b'After=hstn-desktop-overlay.service\n', b'')
        unit.write_bytes(content)
        samples = self.m.templates(ROOT, self.installer.LINKS)
        self.assertIn(unit, self.m.user_files(self.locations, samples, legacy=True))
        unit.write_bytes(content.replace(b'ExecStart=', b'ExecStart=/my/custom/command '))
        with self.assertRaisesRegex(RuntimeError, 'unrecognized'):
            self.m.user_files(self.locations, samples, legacy=True)

    def test_uninstall_prunes_empty_runtime_and_removes_completed_state(self):
        (self.locations.runtime/'scripts').mkdir(parents=True)
        self.locations.state.parent.mkdir(parents=True)
        self.locations.state.write_text(json.dumps({'version': 1, 'files': {}, 'metadata': {'phase': 'removed'}}))
        self.m.finish(self.locations)
        self.assertFalse(self.locations.runtime.exists()); self.assertFalse(self.locations.state.parent.exists())

    def test_legacy_desktop_journal_restores_original_icons_before_cleaning_records(self):
        desktop = load('desktop-integration')
        icon = self.locations.desktop/'hstn-open.desktop'
        icon.parent.mkdir(); icon.write_text('original user icon')
        generated = desktop.install_files(ROOT, self.home, self.locations.data,
            self.locations.config, self.locations.desktop)
        desktop.apply_files(generated, self.locations.desktop_state)
        self.assertEqual(self.installer.remove_user(self.locations), [])
        self.assertEqual(icon.read_text(), 'original user icon')
        self.assertFalse(self.locations.desktop_state.exists())
        samples = self.m.templates(ROOT, self.installer.LINKS)
        plan = self.m.user_files(self.locations, samples, legacy=True,
            originals={icon: self.m.state.file(b'original user icon')})
        self.assertNotIn(icon, plan)
        self.m.apply_files(plan, self.locations); self.m.finish(self.locations)
        self.assertFalse(self.locations.state.parent.exists())

    def test_cleanup_journal_replays_pending_library_edits(self):
        library = self.home/'Steam/shortcuts.vdf'
        library.parent.mkdir(); library.write_bytes(b'original')
        plan = {library: b'updated'}
        original = self.m.state.restore
        def fail_after(path, value):
            original(path, value)
            if path == library: raise OSError('interrupted')
        with patch.object(self.m.state, 'restore', side_effect=fail_after):
            with self.assertRaises(OSError): self.m.apply_files(plan, self.locations)
        self.m.apply_files(plan, self.locations)
        self.assertEqual(library.read_bytes(), b'updated')

    def test_restored_original_exemption_survives_interrupted_clean_slate(self):
        command = self.locations.bin/'switch-to-steam'
        command.parent.mkdir(parents=True); command.write_bytes(b'unrelated original')
        with self.installer.state.Store(self.locations.state, [command]) as store:
            store.apply({command: self.installer.state.file((ROOT/'scripts/switch-to-steam').read_bytes())})
        originals = {command: self.m.state.file(b'unrelated original')}
        self.m.apply_files({}, self.locations, originals=originals)
        self.assertEqual(self.installer.remove_user(self.locations), [])
        recovered = self.m.saved_originals(self.locations, self.installer.allowed_paths(self.locations))
        plan = self.m.user_files(self.locations, self.m.templates(ROOT, self.installer.LINKS), legacy=True, originals=recovered)
        self.assertNotIn(command, plan)
        self.m.apply_files(plan, self.locations)
        self.m.finish(self.locations)
        self.assertEqual(command.read_bytes(), b'unrelated original')
        self.assertFalse(self.locations.state.parent.exists())

    def test_cli_clean_slate_after_previous_uninstall_leaves_no_user_deployment(self):
        command = self.locations.bin/'switch-to-steam'
        command.parent.mkdir(parents=True); command.write_bytes((ROOT/'scripts/switch-to-steam').read_bytes())
        self.locations.state.parent.mkdir(parents=True)
        self.locations.state.write_text(json.dumps({'version': 1, 'files': {}, 'metadata': {
            'phase': 'removed', 'desktop': str(self.locations.desktop)}}))
        def command_runner(args, **kwargs):
            return subprocess.CompletedProcess(args, 3 if 'is-active' in args else 0, 'inactive' if 'is-active' in args else '', '')
        environment = {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.locations.config),
                       'XDG_DATA_HOME': str(self.locations.data), 'XDG_STATE_HOME': str(self.locations.state.parent.parent), 'XDG_RUNTIME_DIR': str(self.home/'run')}
        with patch.dict(os.environ, environment), patch.object(self.installer, 'desktop_idle', return_value=[]), \
             patch.object(self.installer, 'run', side_effect=command_runner), patch.object(self.installer.os, 'geteuid', return_value=1000):
            self.assertEqual(self.installer.main(['uninstall', '--clean-slate', '--user-only']), 0)
        self.assertFalse(command.exists())
        self.assertFalse(self.locations.state.parent.exists())
        self.assertTrue((ROOT/'manifest.json').exists())

    def test_ordinary_uninstall_resumes_with_only_cleanup_record_remaining(self):
        library = self.home/'Steam/shortcuts.vdf'
        library.parent.mkdir(); library.write_bytes(b'updated library')
        self.m.apply_files({library: b'updated library'}, self.locations)
        self.assertFalse(self.locations.state.exists())
        def command_runner(args, **kwargs):
            if args[0] == 'xdg-user-dir': return subprocess.CompletedProcess(args, 0, str(self.locations.desktop), '')
            return subprocess.CompletedProcess(args, 3 if 'is-active' in args else 0, 'inactive' if 'is-active' in args else '', '')
        environment = {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.locations.config),
                       'XDG_DATA_HOME': str(self.locations.data), 'XDG_STATE_HOME': str(self.locations.state.parent.parent), 'XDG_RUNTIME_DIR': str(self.home/'run')}
        with patch.dict(os.environ, environment), patch.object(self.installer, 'desktop_idle', return_value=[]), \
             patch.object(self.installer, 'run', side_effect=command_runner), patch.object(self.installer.os, 'geteuid', return_value=1000):
            self.assertEqual(self.installer.main(['uninstall', '--user-only']), 0)
        self.assertFalse(self.locations.state.parent.exists())
        self.assertEqual(library.read_bytes(), b'updated library')


class CleanSystemTest(unittest.TestCase):
    def test_root_clean_slate_removes_legacy_files_and_disables_guard(self):
        import subprocess
        m = load('install-system')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            helper = root/'usr/local/libexec/session-switch-input-guard.py'
            helper.parent.mkdir(parents=True); helper.write_bytes((ROOT/'scripts/session-switch-input-guard.py').read_bytes())
            unit = root/'etc/systemd/system/session-switch-input-guard.service'
            unit.parent.mkdir(parents=True); unit.write_bytes((ROOT/'templates/systemd/session-switch-input-guard.service').read_bytes())
            states = {'active': True, 'enabled': True}
            def command(args, **kwargs):
                if '--property=FragmentPath' in args: return subprocess.CompletedProcess(args, 0, str(unit) if unit.exists() else '', '')
                if 'is-active' in args: return subprocess.CompletedProcess(args, 0, 'active' if states['active'] else 'inactive', '')
                if 'is-enabled' in args: return subprocess.CompletedProcess(args, 0, 'enabled' if states['enabled'] else 'disabled', '')
                if 'stop' in args: states['active'] = False
                if 'disable' in args: states['enabled'] = False
                return subprocess.CompletedProcess(args, 0, '', '')
            m.clean_system(ROOT, root, command)
            self.assertEqual(states, {'active': False, 'enabled': False})
            self.assertFalse(helper.exists()); self.assertFalse(unit.exists())
            self.assertFalse(m.record_path(root).parent.exists())
            m.clean_system(ROOT, root, command)

    def test_root_cleanup_is_narrow_and_rejects_changed_guard(self):
        m = load('install-system')
        self.assertTrue(hasattr(m, 'legacy_system_files'), 'root clean-slate inventory is missing')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            helper = root/'usr/local/libexec/session-switch-input-guard.py'
            helper.parent.mkdir(parents=True); helper.write_bytes((ROOT/'scripts/session-switch-input-guard.py').read_bytes())
            unrelated = root/'etc/sddm.conf.d/zz-bazzite-autologin.conf'
            unrelated.parent.mkdir(parents=True); unrelated.write_text('[Autologin]\nUser=test\n')
            plan = m.legacy_system_files(ROOT, root)
            self.assertIn(helper, plan); self.assertNotIn(unrelated, plan)
            helper.write_text('unrecognized root code')
            with self.assertRaisesRegex(RuntimeError, 'unrecognized|edited'):
                m.legacy_system_files(ROOT, root)
