import importlib.util
from pathlib import Path
import tempfile
import unittest
from PySide6 import QtCore

SCRIPT=Path(__file__).resolve().parents[1]/'src/session-overlay.py'
spec=importlib.util.spec_from_file_location('switching_overlay',SCRIPT)
overlay=importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)

class SwitchingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def test_request_runs_guard_in_independent_user_unit(self):
        args=overlay.switch_command(Path('/home/test/.local/bin/session-switch'),'desktop')
        self.assertIn('--user',args)
        self.assertIn('--wait',args)
        self.assertIn('--setenv=XDG_CURRENT_DESKTOP=gamescope',args)
        self.assertEqual(args[-3:],['--','/home/test/.local/bin/session-switch','desktop'])
        with self.assertRaises(ValueError):overlay.switch_command(Path('/tmp/helper'),'bad')

    def run_result(self,code,detail):
        with tempfile.TemporaryDirectory() as folder:
            program=Path(folder)/'fake-runner'
            program.write_text(f'#!/bin/sh\necho "{detail}" >&2\nexit {code}\n')
            program.chmod(0o755)
            request=overlay.SwitchRequest(runner=str(program))
            results=[];loop=QtCore.QEventLoop()
            request.completed.connect(lambda *args:(results.append(args),loop.quit()))
            self.assertTrue(request.start('desktop'))
            self.assertFalse(request.start('steam'))
            QtCore.QTimer.singleShot(3000,loop.quit)
            loop.exec()
            self.assertEqual(len(results),1)
            self.assertFalse(request.busy)
            return results[0]

    def test_detected_game_denial_reaches_ui(self):
        code,message=self.run_result(20,'Close running games before switching sessions: Steam 892970')
        self.assertEqual(code,20)
        self.assertIn('Close running games',message)
        self.assertIn('892970',message)

    def test_failure_is_not_reported_as_success(self):
        code,message=self.run_result(21,'Game activity check failed')
        self.assertEqual(code,21)
        self.assertIn('failed',message)

    def test_success_reports_completion(self):
        code,message=self.run_result(0,'Switching to target')
        self.assertEqual(code,0)
        self.assertIn('Switching',message)
