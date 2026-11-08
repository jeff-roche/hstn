import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/session-switch'


class SessionSwitchTest(unittest.TestCase):
    def run_switch(self, target, activity_status=0, desktop='gamescope', helper_exists=True, guard_status=0):
        self.assertTrue(SCRIPT.exists(), 'Guarded session-switch has not been implemented')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); log=root/'calls'
            bin_dir=root/'bin';bin_dir.mkdir()
            helper=bin_dir/'activity'
            guard=bin_dir/'transition-guard.py'
            guard.write_text('import os\nwith open(os.environ["CALLS"],"a") as f:f.write("lid-guard\\n")\n'+f'raise SystemExit({guard_status})\n')
            if helper_exists:
                helper.write_text(f'#!/bin/bash\necho activity >> "$CALLS"\nexit {activity_status}\n')
                helper.chmod(0o755)
            for name in ('busctl','systemctl','steamosctl','qdbus-qt6','notify-send'):
                command=bin_dir/name
                command.write_text('#!/bin/bash\necho "'+name+' $*" >> "$CALLS"\nexit 0\n')
                command.chmod(0o755)
            env=dict(os.environ,PATH=str(bin_dir)+':'+os.environ['PATH'],CALLS=str(log),
                     SESSION_SWITCH_ACTIVITY_HELPER=str(helper),SESSION_SWITCH_TRANSITION_GUARD=str(guard),XDG_CURRENT_DESKTOP=desktop)
            result=subprocess.run(['bash',str(SCRIPT),target],env=env,capture_output=True,text=True)
            return result,log.read_text().splitlines() if log.exists() else []

    def test_detected_game_blocks_every_transition_before_any_session_change(self):
        for target in ('steam','heroic','desktop'):
            with self.subTest(target=target):
                result,calls=self.run_switch(target,20)
                self.assertEqual(result.returncode,20)
                self.assertEqual(calls[0],'activity')
                self.assertNotIn('lid-guard',calls)
                self.assertFalse(any(c.startswith(('busctl','systemctl','steamosctl','qdbus')) for c in calls))

    def test_allowed_gaming_switch_selects_target_then_stops_session(self):
        result,calls=self.run_switch('steam')
        self.assertEqual(result.returncode,0)
        self.assertEqual(calls[0],'activity')
        self.assertEqual(calls[1],'lid-guard')
        self.assertIn('SetTemporarySession s gamescope-session-ogui-steam.desktop',calls[2])
        self.assertTrue(calls[-1].startswith('systemctl --user stop '))

    def test_desktop_transition_checks_before_steamosctl(self):
        result,calls=self.run_switch('desktop')
        self.assertEqual(result.returncode,0)
        self.assertEqual(calls,['activity','lid-guard','steamosctl switch-to-desktop-mode'])

    def test_lid_guard_failure_aborts_before_session_selection_or_logout(self):
        for target in ('steam','heroic','desktop'):
            result,calls=self.run_switch(target,guard_status=1)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(calls,['activity','lid-guard'])

    def test_already_in_desktop_does_not_check_or_switch(self):
        result,calls=self.run_switch('desktop',20,desktop='KDE')
        self.assertEqual(result.returncode,0)
        self.assertEqual(calls,[])

    def test_missing_activity_helper_blocks_switch(self):
        result,calls=self.run_switch('heroic',helper_exists=False)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any(c.startswith(('busctl','systemctl','steamosctl','qdbus')) for c in calls))

    def test_activity_probe_failure_blocks_switch(self):
        result,calls=self.run_switch('heroic',21)
        self.assertEqual(result.returncode,21)
        self.assertFalse(any(c.startswith(('busctl','systemctl','steamosctl','qdbus')) for c in calls))


if __name__ == '__main__':
    unittest.main()
