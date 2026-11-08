import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load():
    spec=importlib.util.spec_from_file_location('capture',ROOT/'scripts/capture-doctor.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class CaptureTests(unittest.TestCase):
    def test_steam_capture_uses_current_single_output_mode(self):
        m=load()
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);(state/'doctor-steam.once').touch()
            result=subprocess.CompletedProcess([],0,'{"ok":true}','')
            with patch.dict(os.environ,{'SESSION_SWITCH_INPUT_TARGET':'ds5-single'}),patch.object(m.subprocess,'run',return_value=result) as run:
                m.capture('steam',os.getpid(),state,delay=0)
                self.assertEqual(run.call_args.kwargs['env']['SESSION_SWITCH_INPUT_TARGET'],'ds5-single')

    def test_unarmed_never_runs_doctor(self):
        m=load()
        with tempfile.TemporaryDirectory() as directory, patch.object(m.subprocess,'run') as run:
            self.assertIsNone(m.capture('steam',os.getpid(),Path(directory),delay=0))
            run.assert_not_called()

    def test_one_shot_failure_is_saved_privately_with_context(self):
        m=load()
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);(state/'doctor-heroic.once').touch()
            result=subprocess.CompletedProcess([],1,json.dumps({'ok':False,'summary':{'FAIL':1}}),'')
            with patch.object(m.subprocess,'run',return_value=result) as run:
                report=m.capture('heroic',os.getpid(),state,delay=0)
                self.assertIsNone(m.capture('heroic',os.getpid(),state,delay=0))
                run.assert_called_once()
                self.assertEqual(run.call_args.kwargs['env']['SESSION_SWITCH_INPUT_TARGET'],'ds5-single')
                self.assertEqual(run.call_args.kwargs['env']['XDG_CURRENT_DESKTOP'],'gamescope')
            data=json.loads(report.read_text())
            self.assertEqual(data['doctor_exit_code'],1)
            self.assertFalse(data['doctor']['ok'])
            self.assertEqual(report.stat().st_mode & 0o777,0o600)

    def test_timeout_is_recorded_without_blocking_launcher(self):
        m=load()
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);(state/'doctor-steam.once').touch()
            with patch.object(m.subprocess,'run',side_effect=subprocess.TimeoutExpired('doctor',60)):
                report=m.capture('steam',os.getpid(),state,delay=0)
            self.assertIn('timed out',json.loads(report.read_text())['error'])

    def test_exited_parent_is_not_reported_as_a_live_session(self):
        m=load()
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory);(state/'doctor-steam.once').touch()
            with patch.object(m,'parent_alive',return_value=False), patch.object(m.subprocess,'run') as run:
                report=m.capture('steam',123,state,delay=0)
            run.assert_not_called()
            self.assertIn('ended',json.loads(report.read_text())['error'])
