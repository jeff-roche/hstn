import json
import importlib.util
from unittest import mock
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class SteamOverlayWrapperTest(unittest.TestCase):
    def test_preserves_packaged_client_arguments_without_shell_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bin_dir=root/'.local/bin';bin_dir.mkdir(parents=True)
            output=root/'arguments.json'
            wrapper=bin_dir/'gamescope-client-with-overlay'
            wrapper.write_text('#!/usr/bin/python3\nimport json,os,sys\nopen(os.environ["OUTPUT"],"w").write(json.dumps(sys.argv[1:]))\n')
            wrapper.chmod(0o755)
            command='steam -gamepadui --label "hello world" "$(touch /tmp/must-not-run)"'
            env=dict(os.environ,HOME=str(root),OUTPUT=str(output),SESSION_SWITCH_STEAM_CLIENTCMD=command,SESSION_SWITCH_ENABLE_STEAM_OVERLAY="1")
            result=subprocess.run([str(ROOT/'scripts/steam-session-with-overlay')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(output.read_text()),['steam','-gamepadui','--label','hello world','$(touch /tmp/must-not-run)'])

    def test_bazzite_disabled_override_wraps_packaged_steam_instead_of_reenabling_ogui(self):
        template = (ROOT/'templates/config/gamescope-session-plus/sessions.d/ogui-steam').read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendor = root/'steam'
            vendor.write_text('export CLIENTCMD=\'steam -gamepadui -steamos3 --label "hello world"\'\n')
            script = template.replace('/usr/share/gamescope-session-plus/sessions.d/steam', str(vendor))
            script += '\npython3 -c \'import json,os; print(json.dumps([os.environ["SESSION_SWITCH_STEAM_CLIENTCMD"],os.environ["CLIENTCMD"]]))\'\n'
            result = subprocess.run(['bash', '-c', script], env={**os.environ, 'HOME': directory},
                                    capture_output=True, text=True, check=True)
            original, wrapped = json.loads(result.stdout)
            self.assertEqual(original, 'steam -gamepadui -steamos3 --label "hello world"')
            self.assertEqual(wrapped, directory+'/.local/bin/steam-session-with-overlay')
            self.assertNotIn('/sessions.d/ogui-steam', template)

    def test_opengamepadui_client_is_executed_without_our_overlay_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);program=root/'opengamepadui';output=root/'args.json'
            program.write_text('#!/usr/bin/python3\nimport json,os,sys\nopen(os.environ["OUTPUT"],"w").write(json.dumps(sys.argv[1:]))\n')
            program.chmod(0o755)
            env=dict(os.environ,HOME=str(root),OUTPUT=str(output),SESSION_SWITCH_STEAM_CLIENTCMD=f'{program} --overlay-mode -- steam -gamepadui')
            result=subprocess.run([str(ROOT/'scripts/steam-session-with-overlay')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('custom overlay not started',result.stderr)
            self.assertEqual(json.loads(output.read_text()),['--overlay-mode','--','steam','-gamepadui'])


    def test_explicit_optout_keeps_steam_overlay_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);program=root/'steam';output=root/'args.json'
            program.write_text('#!/usr/bin/python3\nimport json,os,sys\nopen(os.environ["OUTPUT"],"w").write(json.dumps(sys.argv[1:]))\n')
            program.chmod(0o755)
            env=dict(os.environ,HOME=str(root),OUTPUT=str(output),SESSION_SWITCH_STEAM_CLIENTCMD=f'{program} -gamepadui')
            env['SESSION_SWITCH_ENABLE_STEAM_OVERLAY']='0'
            result=subprocess.run([str(ROOT/'scripts/steam-session-with-overlay')],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(output.read_text()),['-gamepadui'])

    def test_diagnostic_marker_is_consumed_for_one_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local = root / '.local/bin'
            local.mkdir(parents=True)
            program = local / 'steam-session-with-overlay'
            program.write_bytes((ROOT / 'scripts/steam-session-with-overlay').read_bytes())
            program.chmod(0o755)
            (local / 'collect-controller-routes.py').write_text('pass\n')
            wrapper = local / 'gamescope-client-with-overlay'
            wrapper.write_text('#!/bin/sh\nexit 37\n')
            wrapper.chmod(0o755)
            marker = root / '.local/state/session-switch/steam-overlay-diagnostic.once'
            marker.parent.mkdir(parents=True)
            marker.touch()
            env = dict(os.environ, HOME=str(root), SESSION_SWITCH_STEAM_CLIENTCMD='/bin/true')
            env.pop('SESSION_SWITCH_ENABLE_STEAM_OVERLAY', None)
            first = subprocess.run([str(program)], env=env, capture_output=True)
            self.assertEqual(first.returncode, 37, first.stderr)
            self.assertFalse(marker.exists())
            second = subprocess.run([str(program)], env=env, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stderr)

    def test_permanent_guard_enables_normal_steam_without_diagnostics(self):
        # Extensionless executable needs an explicit loader.
        from importlib.machinery import SourceFileLoader
        spec=importlib.util.spec_from_loader('steam_guard_wrapper',SourceFileLoader('steam_guard_wrapper',str(ROOT/'scripts/steam-session-with-overlay')))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ,{'HOME':directory,'SESSION_SWITCH_STEAM_CLIENTCMD':'steam -gamepadui'},clear=True), \
             mock.patch.object(module,'permanent_guard_active',return_value=True), mock.patch.object(module.os,'execv') as wrap, \
             mock.patch.object(module.os,'execvp') as direct, mock.patch.object(module.subprocess,'Popen') as collector:
            module.main()
            wrap.assert_called_once();direct.assert_not_called();collector.assert_not_called()
            self.assertEqual(os.environ['SESSION_SWITCH_REQUIRE_INPUT_GUARD'],'1')

    def test_permanent_guard_absent_keeps_steam_native(self):
        from importlib.machinery import SourceFileLoader
        spec=importlib.util.spec_from_loader('steam_no_guard',SourceFileLoader('steam_no_guard',str(ROOT/'scripts/steam-session-with-overlay')))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ,{'HOME':directory,'SESSION_SWITCH_STEAM_CLIENTCMD':'steam -gamepadui'},clear=True), \
             mock.patch.object(module,'permanent_guard_active',return_value=False), mock.patch.object(module.os,'execv') as wrap, \
             mock.patch.object(module.os,'execvp',side_effect=SystemExit(0)) as direct:
            with self.assertRaises(SystemExit):module.main()
            direct.assert_called_once();wrap.assert_not_called()

if __name__=='__main__':unittest.main()
