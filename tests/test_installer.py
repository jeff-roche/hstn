import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/('installer' if name in ('install-hstn', 'install-system', 'install-state', 'clean-installation', 'remove-launcher-assets') else 'scripts')/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'installer/install-hstn.py').is_file(), 'installer is missing')
        self.m = load('install-hstn')
        self.tmp = tempfile.TemporaryDirectory(prefix='hstn install space ')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = {'HOME': str(self.home), 'XDG_DATA_HOME': str(self.home/'Data'),
                    'XDG_CONFIG_HOME': str(self.home/'Config'), 'XDG_STATE_HOME': str(self.home/'State'), 'XDG_RUNTIME_DIR': str(self.home/'run')}
        self.locations = self.m.Locations(self.home, self.env, self.home/'Desk top')
        # Filesystem lifecycle uses a miniature real release; archive tests cover
        # the actual artwork bytes and complete payload independently.
        self.source = self.home/'release'
        builder = self.m.load('package', 'installer/package.py')
        for name in builder.inventory(ROOT):
            path = self.source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture artwork' if name.startswith('assets/') else (ROOT/name).read_bytes())

    def test_system_phase_stages_installer_helpers_before_execution(self):
        from types import SimpleNamespace
        stage = '/var/tmp/hstn-install.test'
        calls = []

        def run(args, **kwargs):
            calls.append([str(arg) for arg in args])
            return SimpleNamespace(stdout=stage if '/usr/bin/mktemp' in args else '')

        with patch.object(self.m, 'desktop_idle', return_value=[]), patch.object(self.m, 'run', side_effect=run):
            self.m.system_phase('install')
        mkdir = next(args for args in calls if '/usr/bin/install' in args and '-d' in args)
        self.assertIn(stage + '/installer', mkdir)
        self.assertIn(stage + '/templates/systemd', mkdir)
        execution = next(args for args in calls if '/usr/bin/python3' in args)
        self.assertIn(stage + '/installer/install-system.py', execution)
        for name in ('install-system.py', 'install-state.py'):
            self.assertTrue(any(args[-1] == stage + '/installer/' + name for args in calls))

    def test_user_lifecycle_migrates_desktop_backups_and_preserves_edits(self):
        desktop = load('desktop-integration')
        files = desktop.install_files(ROOT, self.home, self.locations.data, self.locations.config, self.locations.desktop)
        icon = self.locations.desktop/'hstn-open.desktop'
        icon.parent.mkdir()
        icon.write_text('original icon')
        desktop.apply_files(files, self.locations.desktop_state)
        plan = self.m.user_files(self.source, self.locations)
        self.m.apply_user(self.source, self.locations, plan)
        self.m.apply_user(self.source, self.locations, plan)
        self.assertEqual((self.home/'.local/bin/hstn').resolve(), self.locations.runtime/'scripts/hstn')
        self.assertTrue((self.locations.runtime/'manifest.json').exists())
        self.assertFalse(self.locations.desktop_state.exists())
        icon.write_text('later edit')
        conflicts = self.m.remove_user(self.locations)
        self.assertIn(str(icon), conflicts)
        self.assertEqual(icon.read_text(), 'later edit')
        icon.write_text(plan[icon]['data'] and self.m.state.base64.b64decode(plan[icon]['data']).decode())
        self.assertEqual(self.m.remove_user(self.locations), [])
        self.assertEqual(icon.read_text(), 'original icon')

    def test_native_package_owns_runtime_and_standalone_refuses(self):
        with patch.object(self.m, 'native_installation', return_value=Path('/usr/lib/hstn')):
            with self.assertRaisesRegex(RuntimeError, 'package manager'):
                self.m.user_files(self.source, self.locations)
        native = self.home/'native'
        native.mkdir()
        (native/'PACKAGE-MANAGED').write_text('native')
        # Native setup consumes the package tree, without making a private runtime copy.
        with patch.object(self.m, 'native_installation', return_value=native):
            plan = self.m.user_files(self.source, self.locations, package=True)
        self.assertFalse(any(self.locations.runtime in path.parents for path in plan))

    def test_failed_preflight_does_not_create_installation_state(self):
        with patch.object(self.m.os, 'geteuid', return_value=1000), patch.object(self.m.shutil, 'which', return_value=None):
            errors = self.m.preflight(ROOT, self.locations, {}, configure=False)
        self.assertTrue(any('missing' in e.lower() for e in errors))
        self.assertFalse(self.locations.state.exists())
        self.assertFalse(self.locations.runtime.exists())

    def test_home_alias_is_resolved_but_nested_managed_symlinks_are_rejected(self):
        alias = self.home/'home-alias'
        real = self.home/'real-home'
        real.mkdir()
        alias.symlink_to(real, target_is_directory=True)
        locations = self.m.Locations(alias, {}, alias/'Desktop')
        self.assertEqual(locations.home, real)
        target = self.home/'elsewhere'
        target.mkdir()
        (real/'.local').mkdir()
        (real/'.local/bin').symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.m.validate_user_plan(locations, self.m.user_files(self.source, locations))

    def test_tampered_desktop_record_cannot_migrate_unrelated_paths(self):
        self.locations.desktop_state.parent.mkdir(parents=True)
        self.locations.desktop_state.write_text(json.dumps({'version': 1, 'files': {
            str(self.home/'unrelated'): {'previous': None, 'installed': self.m.state.file(b'x')}}}))
        with self.assertRaisesRegex(RuntimeError, 'path'):
            self.m.apply_user(self.source, self.locations, self.m.user_files(self.source, self.locations))
        self.assertFalse(self.locations.runtime.exists())

    def test_desktop_record_with_legacy_home_alias_migrates(self):
        alias = self.home/'home-alias'
        alias.symlink_to(self.home, target_is_directory=True)
        icon = self.locations.desktop/'hstn-open.desktop'
        icon.parent.mkdir()
        icon.write_text('legacy installed icon')
        self.locations.desktop_state.parent.mkdir(parents=True)
        self.locations.desktop_state.write_text(json.dumps({'version': 1, 'files': {
            str(alias/'Desk top/hstn-open.desktop'): {
                'installed': self.m.state.file(b'legacy installed icon'),
                'previous': self.m.state.file(b'original icon')}}}))
        self.m.apply_user(self.source, self.locations, self.m.user_files(self.source, self.locations))
        self.assertEqual(self.m.remove_user(self.locations), [])
        self.assertEqual(icon.read_text(), 'original icon')

    def test_focused_desktop_setup_respects_general_installer_ownership(self):
        plan = self.m.user_files(self.source, self.locations)
        self.m.apply_user(self.source, self.locations, plan)
        desktop = load('desktop-integration')
        with patch.dict(os.environ, {'XDG_STATE_HOME': str(self.home/'State')}):
            with self.assertRaisesRegex(RuntimeError, 'general installer'):
                desktop.apply_files({self.locations.desktop/'hstn-open.desktop': ('replacement', 0o755)}, self.locations.desktop_state)
        self.assertFalse(self.locations.desktop_state.exists())
        self.assertEqual(self.m.remove_user(self.locations), [])

    def test_permission_override_restores_existing_policy_and_preserves_later_edits(self):
        self.locations.override.parent.mkdir(parents=True)
        before = '[Session Bus Policy]\norg.freedesktop.Flatpak=none\norg.example.Other=talk\n'
        self.locations.override.write_text(before)
        doctor = load('mechanic')
        original_load = self.m.load
        with patch.object(doctor, 'permission_check', return_value=('FAIL', 'denied')):
            with patch.object(self.m, 'load', side_effect=lambda name, *a: doctor if name == 'mechanic' else original_load(name, *a)):
                permission = self.m.permission_file(self.locations)
        plan = self.m.user_files(self.source, self.locations)
        plan.update(permission)
        self.m.apply_user(self.source, self.locations, plan)
        self.assertIn('org.freedesktop.Flatpak=talk', self.locations.override.read_text())
        self.assertIn('org.example.Other=talk', self.locations.override.read_text())
        self.assertEqual(self.m.remove_user(self.locations), [])
        self.assertEqual(self.locations.override.read_text(), before)

    def test_upgrade_retains_owned_permission_when_already_effective(self):
        first = self.m.user_files(self.source, self.locations)
        first[self.locations.override] = self.m.state.file(b'[Session Bus Policy]\norg.freedesktop.Flatpak=talk\n')
        self.m.apply_user(self.source, self.locations, first)
        self.m.apply_user(self.source, self.locations, self.m.user_files(self.source, self.locations))
        self.assertTrue(self.locations.override.exists())
        self.assertEqual(self.m.remove_user(self.locations), [])
        self.assertFalse(self.locations.override.exists())

    def test_retired_file_restoration_can_resume_after_interruption(self):
        first = self.m.user_files(self.source, self.locations)
        retired = self.locations.runtime/'old-helper'
        retired.parent.mkdir(parents=True)
        retired.write_text('original collision')
        first[retired] = self.m.state.file(b'old installed helper')
        self.m.apply_user(self.source, self.locations, first)
        original = self.m.state.restore
        def interrupt(path, value):
            original(path, value)
            if path == retired:
                raise OSError('interrupted after restore')
        # apply_user computes retirement only on the new plan.
        with patch.object(self.m.state, 'restore', side_effect=interrupt):
            with self.assertRaises(OSError):
                self.m.apply_user(self.source, self.locations, self.m.user_files(self.source, self.locations))
        self.m.apply_user(self.source, self.locations, self.m.user_files(self.source, self.locations))
        self.assertEqual(retired.read_text(), 'original collision')

    def test_close_flag_closes_only_detected_launchers_without_prompting(self):
        with patch.object(self.m, 'desktop_idle', return_value=[]), \
             patch.object(self.m, 'running_launchers', side_effect=[['Steam', 'Heroic'], ['Steam', 'Heroic'], ['Heroic'], []]), \
             patch.object(self.m.shutil, 'which', return_value='/usr/bin/steam'), \
             patch.object(self.m, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as command, \
             patch.object(self.m, 'request_heroic_close') as heroic, patch('builtins.input') as prompt:
            self.m.close_running_launchers()
        command.assert_called_once_with(['steam', '-shutdown'], check=False, timeout=20)
        heroic.assert_called_once()
        prompt.assert_not_called()

    def test_close_flag_does_not_close_launchers_when_game_or_session_blocks(self):
        for error in ('Games must be closed', 'An active Gamescope session prevents installation/removal'):
            with self.subTest(error=error), patch.object(self.m, 'desktop_idle', return_value=[error]), \
                 patch.object(self.m, 'run') as command, patch.object(self.m, 'request_heroic_close') as heroic:
                with self.assertRaisesRegex(RuntimeError, error):
                    self.m.close_running_launchers()
                command.assert_not_called()
                heroic.assert_not_called()

    def test_close_flag_rechecks_games_before_each_launcher(self):
        with patch.object(self.m, 'desktop_idle', side_effect=[[], ['Games must be closed']]), \
             patch.object(self.m, 'running_launchers', return_value=['Steam']), \
             patch.object(self.m, 'run') as command:
            with self.assertRaisesRegex(RuntimeError, 'Games must be closed'):
                self.m.close_running_launchers()
            command.assert_not_called()

    def test_close_flag_reports_launchers_that_do_not_exit(self):
        with patch.object(self.m, 'desktop_idle', return_value=[]), \
             patch.object(self.m, 'running_launchers', return_value=['Heroic']), \
             patch.object(self.m, 'request_heroic_close') as heroic:
            with self.assertRaisesRegex(RuntimeError, 'Close these launchers manually, then retry: Heroic'):
                self.m.close_running_launchers(timeout=0)
            heroic.assert_called_once()

    def test_close_flag_handles_flatpak_only_steam(self):
        with patch.object(self.m, 'desktop_idle', return_value=[]), \
             patch.object(self.m, 'running_launchers', side_effect=[['Steam'], ['Steam'], []]), \
             patch.object(self.m.shutil, 'which', return_value=None), \
             patch.object(self.m, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as command:
            self.m.close_running_launchers()
        command.assert_called_once_with(['flatpak', 'run', 'com.valvesoftware.Steam', '-shutdown'], check=False, timeout=20)

    def test_heroic_close_targets_main_process_and_preserves_renderers_and_other_apps(self):
        proc = self.home/'proc'
        proc.mkdir()
        for pid, name, args in ((100, 'heroic', b'/app/heroic\0'),
                                (101, 'heroic', b'/app/heroic\0--type=renderer\0'),
                                (102, 'game', b'/game\0')):
            process = proc/str(pid)
            process.mkdir()
            (process/'comm').write_text(name)
            (process/'cmdline').write_bytes(args)
            (process/'stat').write_text(str(pid) + ' (' + name + ') S ' + '0 '*18 + '123')
        with patch.object(self.m.os, 'pidfd_open', return_value=9) as open_pid, \
             patch.object(self.m.signal, 'pidfd_send_signal') as terminate, \
             patch.object(self.m.os, 'close') as close:
            self.m.request_heroic_close(proc)
        open_pid.assert_called_once_with(100)
        terminate.assert_called_once_with(9, self.m.signal.SIGTERM)
        close.assert_called_once_with(9)

    def test_heroic_close_rejects_reused_pid(self):
        proc = self.home/'proc'
        process = proc/'100'
        process.mkdir(parents=True)
        (process/'comm').write_text('heroic')
        (process/'cmdline').write_bytes(b'/app/heroic\0')
        prefix = '100 (heroic) S ' + '0 '*18
        (process/'stat').write_text(prefix + '123')
        def reopen(pid):
            (process/'stat').write_text(prefix + '456')
            return 9
        with patch.object(self.m.os, 'pidfd_open', side_effect=reopen), \
             patch.object(self.m.signal, 'pidfd_send_signal') as terminate, \
             patch.object(self.m.os, 'close') as close:
            self.m.request_heroic_close(proc)
        terminate.assert_not_called()
        close.assert_called_once_with(9)

    def test_preflight_lists_only_launchers_that_are_running(self):
        config = load('configure-launchers')
        desktop = load('desktop-integration')
        for steam, heroic, expected in ((True, False, 'Steam'), (False, True, 'Heroic'),
                                        (True, True, 'Steam, Heroic'), (False, False, None)):
            with self.subTest(steam=steam, heroic=heroic), \
                 patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'KDE'}), \
                 patch.object(self.m, 'load', side_effect=lambda name: desktop if name == 'desktop-integration' else config), \
                 patch.object(desktop, 'gamescope_active', return_value=False), \
                 patch.object(config, 'steam_running', return_value=steam) as check_steam, \
                 patch.object(config, 'heroic_running', return_value=heroic) as check_heroic, \
                 patch.object(self.m, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
                errors = self.m.desktop_idle()
                check_steam.assert_called_once()
                check_heroic.assert_called_once()
                if expected:
                    self.assertEqual(errors, ['Close these running launchers before installation/removal: ' + expected])
                else:
                    self.assertEqual(errors, [])

    def test_ambiguous_configurations_require_explicit_selection(self):
        config = load('configure-launchers')
        original_load = self.m.load
        with patch.object(config, 'detect_config', side_effect=ValueError('Cannot select one steam configuration')):
            with patch.object(self.m, 'load', side_effect=lambda name, *a: config if name == 'configure-launchers' else original_load(name, *a)):
                with self.assertRaisesRegex(ValueError, 'select one'):
                    self.m.selected_configs({})
                steam, heroic = self.home/'steam config', self.home/'heroic config'
                steam.mkdir(); heroic.mkdir()
                self.assertEqual(self.m.selected_configs({'steam_config_dir': steam, 'heroic_config_dir': heroic}),
                                 {'steam': steam, 'heroic': heroic})

    def test_dry_run_is_read_only_and_reports_incomplete_dependencies(self):
        env = dict(os.environ, HOME=str(self.home), XDG_DATA_HOME=str(self.locations.data),
                   XDG_CONFIG_HOME=str(self.locations.config), XDG_STATE_HOME=str(self.locations.state.parent.parent))
        result = subprocess.run(['python3', '-B', str(ROOT/'installer/install.py'), '--dry-run'], env=env,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('HSTN', result.stdout + result.stderr)
        self.assertFalse(self.locations.state.exists())
        self.assertFalse(self.locations.runtime.exists())

    def test_overlay_recovery_restores_previously_active_service(self):
        active = {'hstn-desktop-overlay.service': False, 'session-switch-overlay.service': False}
        def command(args, **kwargs):
            if 'start' in args:
                active[args[-1]] = True
            return subprocess.CompletedProcess(args, 0, '', '')
        self.m.restore_overlays({'hstn-desktop-overlay.service': True, 'session-switch-overlay.service': False}, command)
        self.assertTrue(active['hstn-desktop-overlay.service'])
        self.assertFalse(active['session-switch-overlay.service'])

    def test_launcher_prompts_configure_only_accepted_launcher(self):
        selected = {'steam': self.home/'Steam config', 'heroic': self.home/'Heroic config'}
        with patch.object(self.m, 'confirm_launcher', side_effect=[False, True]) as prompt, \
             patch.object(self.m, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as command:
            self.assertEqual(self.m.configure_installed_launchers(self.source, selected), 0)
        self.assertEqual([call.args[0] for call in prompt.call_args_list], ['steam', 'heroic'])
        args = command.call_args.args[0]
        self.assertIn('--launcher', args)
        self.assertIn('heroic', args)
        self.assertIn('--heroic-config-dir', args)
        self.assertIn(selected['heroic'], args)
        self.assertNotIn('--steam-config-dir', args)
        command.assert_called_once()

    def test_yes_configures_each_launcher_without_prompting(self):
        selected = {'steam': self.home/'Steam config', 'heroic': self.home/'Heroic config'}
        with patch.object(self.m, 'confirm_launcher') as prompt, \
             patch.object(self.m, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as command:
            self.assertEqual(self.m.configure_installed_launchers(self.source, selected, True), 0)
        prompt.assert_not_called()
        self.assertEqual(command.call_count, 2)
        self.assertEqual([call.args[0][4] for call in command.call_args_list], ['steam', 'heroic'])

    def test_launcher_configuration_failure_still_offers_other_launcher(self):
        selected = {'steam': self.home/'steam', 'heroic': self.home/'heroic'}
        results = [subprocess.CompletedProcess([], 1, '', 'Steam is running'),
                   subprocess.CompletedProcess([], 0, '', '')]
        with patch.object(self.m, 'run', side_effect=results) as command:
            self.assertEqual(self.m.configure_installed_launchers(self.source, selected, True), 1)
        self.assertEqual(command.call_count, 2)

    def test_launcher_prompt_retries_invalid_answer_and_accepts_no(self):
        with patch.object(self.m.sys.stdin, 'isatty', return_value=True), \
             patch('builtins.input', side_effect=['maybe', 'n']):
            self.assertFalse(self.m.confirm_launcher('steam'))

    def test_piped_installer_reads_confirmation_from_controlling_terminal(self):
        import io
        reader, writer = io.StringIO('yes\n'), io.StringIO()
        with patch.object(self.m.sys.stdin, 'isatty', return_value=False), \
             patch('builtins.open', side_effect=[reader, writer]) as opened:
            self.assertTrue(self.m.confirm_launcher('heroic'))
        self.assertEqual(opened.call_args_list[0].args, ('/dev/tty',))

    def test_launcher_prompt_skips_without_terminal(self):
        with patch.object(self.m.sys.stdin, 'isatty', return_value=False), \
             patch('builtins.open', side_effect=OSError('No terminal')):
            self.assertFalse(self.m.confirm_launcher('steam'))

    def test_cli_install_repeat_status_uninstall_with_fixture_services(self):
        steam = self.home/'Steam config'
        heroic = self.home/'Heroic config'
        steam.mkdir(); heroic.mkdir()
        active = False
        def command(args, check=True, **kwargs):
            nonlocal active
            strings = [str(a) for a in args]
            if strings[:2] == ['xdg-user-dir', 'DESKTOP']:
                return subprocess.CompletedProcess(args, 0, str(self.locations.desktop), '')
            if 'is-active' in strings:
                value = 'active' if active and strings[-1] == 'hstn-desktop-overlay.service' else 'inactive'
                return subprocess.CompletedProcess(args, 0 if value == 'active' else 3, value, '')
            if 'stop' in strings:
                active = False
            if 'autostart' in strings or 'start' in strings:
                active = True
            return subprocess.CompletedProcess(args, 0, '', '')
        doctor = load('mechanic')
        original_load = self.m.load
        with patch.object(self.m, 'ROOT', self.source), patch.object(self.m.Path, 'home', return_value=self.home), \
             patch.dict(os.environ, self.env), patch.object(self.m.os, 'geteuid', return_value=1000), \
             patch.object(self.m, 'run', side_effect=command), patch.object(self.m, 'preflight', return_value=[]), \
             patch.object(self.m, 'desktop_idle', return_value=[]), patch.object(self.m, 'close_running_launchers') as close_launchers, patch.object(self.m, 'confirm_launcher', return_value=False), patch.object(doctor, 'permission_check', return_value=('PASS', 'allowed')), \
             patch.object(self.m, 'load', side_effect=lambda name, *a: doctor if name == 'mechanic' else original_load(name, *a)):
            options = ['-c', '--user-only', '--steam-config-dir', str(steam), '--heroic-config-dir', str(heroic)]
            self.assertEqual(self.m.main(options), 0)
            self.assertTrue(active)
            self.assertEqual(close_launchers.call_count, 1)
            self.assertEqual(self.m.main([*options, '--dry-run']), 0)
            self.assertEqual(close_launchers.call_count, 1)
            self.assertEqual(self.m.main(options), 0)
            self.assertEqual(close_launchers.call_count, 2)
            self.assertEqual(self.m.main([*options[1:], '-y']), 0)
            self.assertEqual(close_launchers.call_count, 2)
            self.assertEqual(self.m.main(['--status', '-c']), 0)
            self.assertEqual(close_launchers.call_count, 2)
            self.assertEqual(self.m.main(['uninstall', '--user-only']), 0)
        self.assertFalse((self.locations.bin/'hstn').exists())
        self.assertFalse(active)


class SystemInstallerTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'installer/install-system.py').exists(), 'system installer is missing')
        self.m = load('install-system')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_source_reservation_recovery_blocks_removal(self):
        for relative in ('run/session-switch-input-guard/source-reservation.json',
                         'run/udev/rules.d/72-hstn-controller-sources.rules'):
            with self.subTest(relative=relative):
                path=self.root/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text('retained recovery data')
                with self.assertRaisesRegex(RuntimeError,'recovery remains'):
                    self.m.require_guard_recovery_complete(self.root)
                self.assertEqual(path.read_text(),'retained recovery data')
                path.unlink()
        self.m.require_guard_recovery_complete(self.root)

    def test_sddm_plan_preserves_existing_directories_and_does_not_select_session(self):
        config = self.root/'etc/sddm.conf'
        config.parent.mkdir(parents=True)
        config.write_text('[Wayland]\nSessionDir=/custom/sessions,/usr/share/wayland-sessions\n[Autologin]\nUser=someone\nSession=plasma.desktop\n')
        files = self.m.system_files(ROOT, self.root)
        values = [self.m.state.base64.b64decode(value['data']).decode() for value in files.values()]
        snippet = next(value for value in values if value.startswith('[Wayland]'))
        self.assertIn('/custom/sessions', snippet)
        self.assertIn('/etc/wayland-sessions', snippet)
        self.assertNotIn('Autologin', snippet)
        # Main sddm.conf has higher precedence: fail rather than pretending a drop-in works.
        with self.assertRaisesRegex(RuntimeError, 'sddm.conf'):
            self.m.check_sddm_precedence(self.root)

    def test_system_install_repeat_remove_restores_files_and_service_state(self):
        helper = self.root/'usr/local/libexec/session-switch-input-guard.py'
        helper.parent.mkdir(parents=True)
        helper.write_text('previous helper')
        helper.chmod(0o755)
        services = {'enabled': False, 'active': True}
        def command(args, **kwargs):
            if '--property=FragmentPath' in args:
                unit = self.root/'etc/systemd/system/session-switch-input-guard.service'
                return subprocess.CompletedProcess(args, 0, str(unit) if unit.exists() else '', '')
            if 'is-enabled' in args:
                return subprocess.CompletedProcess(args, 0 if services['enabled'] else 1, 'enabled' if services['enabled'] else 'disabled', '')
            if 'is-active' in args:
                return subprocess.CompletedProcess(args, 0 if services['active'] else 3, 'active' if services['active'] else 'inactive', '')
            if 'enable' in args: services['enabled'] = True
            if 'disable' in args: services['enabled'] = False
            if 'stop' in args: services['active'] = False
            if 'start' in args or 'restart' in args: services['active'] = True
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(self.m, 'ready', return_value=True):
            self.m.apply_system(ROOT, self.root, command)
            self.m.apply_system(ROOT, self.root, command)
            self.assertTrue(services['enabled'])
            self.assertEqual(self.m.remove_system(self.root, command), [])
        self.assertEqual(helper.read_text(), 'previous helper')
        self.assertFalse(services['enabled'])
        self.assertTrue(services['active'])

    def test_clean_system_install_does_not_stop_a_nonexistent_guard(self):
        def command(args, **kwargs):
            if '--property=FragmentPath' in args:
                unit = self.root/'etc/systemd/system/session-switch-input-guard.service'
                return subprocess.CompletedProcess(args, 0, str(unit) if unit.exists() else '', '')
            if 'is-enabled' in args:
                return subprocess.CompletedProcess(args, 1, 'not-found', '')
            if 'is-active' in args:
                return subprocess.CompletedProcess(args, 4, 'inactive', '')
            if 'stop' in args:
                raise RuntimeError('Unit not loaded')
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(self.m, 'ready', return_value=True):
            self.m.apply_system(ROOT, self.root, command)
        self.assertTrue((self.root/'etc/systemd/system/session-switch-input-guard.service').exists())

    def test_repeat_system_uninstall_is_a_noop(self):
        record = self.m.record_path(self.root)
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({'version': 1, 'files': {}, 'metadata': {
            'removed': True, 'service': {'enabled': False, 'active': False}}}))
        def command(args, **kwargs):
            raise AssertionError('Repeated removal must not control any service')
        self.assertEqual(self.m.remove_system(self.root, command), [])

    def test_system_uninstall_recovers_after_only_session_file_was_written(self):
        files = self.m.system_files(ROOT, self.root)
        first = next(iter(files))
        with self.m.state.Store(self.m.record_path(self.root), files) as store:
            store.state['metadata']['service'] = {'enabled': False, 'active': False}
            store.apply({first: files[first]})
        def command(args, **kwargs):
            if 'stop' in args or 'disable' in args:
                raise RuntimeError('Guard unit does not exist yet')
            return subprocess.CompletedProcess(args, 1, 'inactive' if 'is-active' in args else 'not-found', '')
        self.assertEqual(self.m.remove_system(self.root, command), [])
        self.assertFalse(first.exists())

    def test_native_plan_does_not_own_packaged_guard_files(self):
        files = self.m.system_files(ROOT, self.root, package=True)
        self.assertFalse(any('libexec' in str(p) or '/systemd/system/' in str(p) for p in files))

    def test_atomic_distribution_usr_local_alias_is_supported(self):
        local = self.root/'usr/local'
        local.parent.mkdir(parents=True)
        target = self.root/'var/usrlocal'
        target.mkdir(parents=True)
        local.symlink_to(target, target_is_directory=True)
        files = self.m.system_files(ROOT, self.root)
        self.assertIn(target/'libexec/session-switch-input-guard.py', files)

    def test_system_record_must_be_private_and_owned_before_loading(self):
        record = self.m.record_path(self.root)
        record.parent.mkdir(parents=True)
        record.parent.chmod(0o700)
        record.write_text('{"version":1,"files":{}}')
        record.chmod(0o600)
        self.m.trusted_record(self.root, owner_uid=os.getuid())
        record.chmod(0o666)
        with self.assertRaisesRegex(RuntimeError, 'ownership|private|trusted'):
            self.m.trusted_record(self.root, owner_uid=os.getuid())
        record.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, 'ownership|private|trusted'):
            self.m.trusted_record(self.root, owner_uid=os.getuid() + 1)
        record.parent.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'ownership|private|trusted'):
            self.m.trusted_record(self.root, owner_uid=os.getuid())

    def test_effective_service_cannot_be_redirected_by_dropins_or_shadow_units(self):
        def dropin(args, **kwargs):
            output = '/etc/systemd/system/session-switch-input-guard.service.d/override.conf' if '--property=DropInPaths' in args else ''
            return subprocess.CompletedProcess(args, 0, output, '')
        with self.assertRaisesRegex(RuntimeError, 'drop-in'):
            self.m.verify_service_layout(self.root, dropin, package=False)
        def shadow(args, **kwargs):
            output = '/etc/systemd/system/session-switch-input-guard.service' if '--property=FragmentPath' in args else ''
            return subprocess.CompletedProcess(args, 0, output, '')
        with self.assertRaisesRegex(RuntimeError, 'fragment|shadow'):
            self.m.verify_service_layout(self.root, shadow, package=True)

    def test_fedora_vendor_timeout_policy_is_preserved_but_cannot_redirect_service(self):
        dropin = self.root/'usr/lib/systemd/system/service.d/10-timeout-abort.conf'
        dropin.parent.mkdir(parents=True)
        dropin.write_text('# Fedora-wide shutdown policy\n[Service]\nTimeoutStopFailureMode=abort\n')
        def command(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, str(dropin) if '--property=DropInPaths' in args else '', '')
        # The fixture root is user-owned; production trust checking still runs
        # against the real root-owned vendor file in the privileged phase.
        with patch.object(self.m, 'trusted_destinations', return_value=None):
            self.m.verify_service_layout(self.root, command)
            self.assertIn('TimeoutStopFailureMode=abort', dropin.read_text())
            dropin.write_text('[Service]\nTimeoutStopFailureMode=abort\nExecStart=/home/user/guard\n')
            with self.assertRaisesRegex(RuntimeError, 'drop-in'):
                self.m.verify_service_layout(self.root, command)
            dropin.write_text('[Service]\nTimeoutStopFailureMode=abort\n')
            with patch.object(self.m, 'trusted_destinations', side_effect=RuntimeError('Untrusted owner')):
                with self.assertRaisesRegex(RuntimeError, 'Untrusted'):
                    self.m.verify_service_layout(self.root, command)
