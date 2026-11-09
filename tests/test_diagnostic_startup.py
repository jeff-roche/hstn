import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DiagnosticStartupTest(unittest.TestCase):
    def run_wrapper(self, ready, heroic=False, arm=True, arm_doctor=False, supported=True):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            local = home / '.local/bin'
            local.mkdir(parents=True)
            runtime = home / 'runtime'
            runtime.mkdir()
            log = home / 'log'
            systemctl = local / 'systemctl'
            systemctl.write_text('#!/bin/sh\necho "systemctl $*" >> "$LOG"\ncase "$*" in *start*) cat "$XDG_RUNTIME_DIR/session-switch-overlay.env" >> "$LOG";; esac\n')
            systemctl.chmod(0o755)
            (local/'wait-controller-isolation.py').write_text(
                'import os,sys\nwith open(os.environ["LOG"],"a") as f: f.write("check\\ncheck-args "+" ".join(sys.argv[1:])+"\\n")\n'
                f'raise SystemExit({0 if ready else 1})\n')
            (local/'supported-controllers.py').write_text('raise SystemExit(' + str(0 if supported else 1) + ')\n')
            marker=home/'.local/state/session-switch/heroic-input-diagnostic.once'
            if heroic:
                if arm:
                    marker.parent.mkdir(parents=True);marker.touch()
                for helper in ('collect-controller-routes.py','collect-gamescope-windows.py','heroic-window-focus.py'):
                    (local/helper).write_text('pass\n')
            doctor_marker=home/'.local/state/hstn'/f'doctor-{"heroic" if heroic else "steam"}.once'
            if arm_doctor:
                doctor_marker.parent.mkdir(parents=True);doctor_marker.touch()
            (local/'capture-doctor.py').write_text('import os,sys\nfrom pathlib import Path\nsession=sys.argv[sys.argv.index("--session")+1]\nPath(os.environ["HOME"],".local/state/hstn",f"doctor-{session}.once").unlink()\nwith open(os.environ["LOG"],"a") as f: f.write("doctor "+session+"\\n")\n')
            client = local / ('heroic-gamescope' if heroic else 'fake-steam')
            client.write_text('#!/bin/sh\necho client >> "$LOG"\n')
            client.chmod(0o755)
            env = dict(os.environ, HOME=str(home), XDG_RUNTIME_DIR=str(runtime),
                       DISPLAY=':999', LOG=str(log),
                       PATH=str(local)+':'+os.environ['PATH'], SESSION_SWITCH_STEAM_DIAGNOSTIC='0' if heroic else '1')
            result = subprocess.run([str(ROOT/'scripts/gamescope-client-with-overlay'),str(client)],
                                    env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((runtime/'session-switch-overlay.env').exists())
            if heroic:self.assertFalse(marker.exists())
            return log.read_text().splitlines()

    def test_no_supported_controller_starts_launcher_without_overlay_or_wait(self):
        for heroic in (False, True):
            with self.subTest(heroic=heroic):
                lines = self.run_wrapper(False, heroic=heroic, supported=False)
                self.assertNotIn('check', lines)
                self.assertIn('systemctl --user start session-switch-overlay.service', lines)
                self.assertIn('client', lines)

    def test_failed_preflight_keeps_watcher_until_client_exits(self):
        lines = self.run_wrapper(False)
        self.assertLess(lines.index('check'),lines.index('systemctl --user stop session-switch-overlay.service'))
        self.assertLess(lines.index('client'),lines.index('systemctl --user stop session-switch-overlay.service'))

    def test_successful_preflight_starts_client_before_cleanup(self):
        lines = self.run_wrapper(True)
        self.assertLess(lines.index('check'),lines.index('client'))
        self.assertLess(lines.index('client'),lines.index('systemctl --user stop session-switch-overlay.service'))

    def test_heroic_one_shot_uses_same_exclusion_gate(self):
        lines = self.run_wrapper(True, heroic=True)
        self.assertLess(lines.index('check'),lines.index('client'))

    def test_failed_heroic_gate_keeps_watcher_until_client_exits(self):
        lines = self.run_wrapper(False, heroic=True)
        self.assertLess(lines.index('client'),lines.index('systemctl --user stop session-switch-overlay.service'))

    def test_heroic_selects_single_playstation_output(self):
        lines=self.run_wrapper(True,heroic=True)
        self.assertIn('SESSION_SWITCH_INPUT_TARGET=ds5-single',lines)

    def test_unarmed_heroic_also_requires_isolation(self):
        lines=self.run_wrapper(False,heroic=True,arm=False)
        self.assertLess(lines.index('client'),lines.index('systemctl --user stop session-switch-overlay.service'))
        self.assertIn('SESSION_SWITCH_INPUT_TARGET=ds5-single',lines)

    def test_steam_requires_one_playstation_output_before_client_starts(self):
        lines=self.run_wrapper(True)
        self.assertIn('SESSION_SWITCH_INPUT_TARGET=ds5-single',lines)
        self.assertIn('check-args --single-playstation',lines)
        self.assertLess(lines.index('check'),lines.index('client'))

    def test_doctor_capture_runs_only_when_armed_for_each_session(self):
        self.assertIn('doctor steam',self.run_wrapper(True,arm_doctor=True))
        self.assertIn('doctor heroic',self.run_wrapper(True,heroic=True,arm_doctor=True))
        self.assertFalse(any(line.startswith('doctor ') for line in self.run_wrapper(True)))
