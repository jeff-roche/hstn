import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/session-close.py'
def load():
    spec=importlib.util.spec_from_file_location('close_execution',SCRIPT)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class CloseExecutionTest(unittest.TestCase):
    def test_confirmed_child_is_closed_and_unrelated_child_survives(self):
        m=load();target=subprocess.Popen(['/bin/sleep','60']);other=subprocess.Popen(['/bin/sleep','60'])
        try:
            record=m.process_record(Path('/proc')/str(target.pid))
            record['heroic_id']='test'
            plan=m.build_plan('desktop',[record],{('heroic','test'):'Test Game'},set(),set(),set())
            empty=dict(plan,apps=[]);switched=[]
            with mock.patch.object(m,'request_window_close'):
                code=m.execute_plan(plan,inspect=mock.Mock(side_effect=[plan,empty]),
                    switch=lambda target:switched.append(target) or 0,grace=0,term_wait=2)
            self.assertEqual(code,0);self.assertEqual(switched,['desktop'])
            target.wait(timeout=2);self.assertIsNone(other.poll())
        finally:
            for process in (target,other):
                if process.poll() is None:process.terminate()
                process.wait()

    def test_new_process_aborts_before_any_close(self):
        m=load();approved=m.build_plan('desktop',[],{},set(),set(),set())
        current=dict(approved,apps=[{'key':['heroic','new'],'label':'New Game','processes':[
            {'pid':123,'start':100,'uid':os.getuid(),'name':'new'}]}])
        with mock.patch.object(m,'request_window_close') as close, mock.patch.object(m.os,'pidfd_open') as open_pid:
            self.assertEqual(m.execute_plan(approved,inspect=lambda _:current),24)
            close.assert_not_called();open_pid.assert_not_called()

    def test_timeout_never_switches_or_force_kills(self):
        m=load();plan=m.build_plan('desktop',[],{},set(),set(),set())
        still=dict(plan,apps=[{'label':'Still running'}]);switch=mock.Mock()
        with mock.patch.object(m,'request_window_close'):
            self.assertEqual(m.execute_plan(plan,inspect=mock.Mock(side_effect=[plan,still]),switch=switch,grace=0,term_wait=0),20)
        switch.assert_not_called()

    def test_plan_is_private_expiring_and_single_use(self):
        m=load()
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ,{'XDG_RUNTIME_DIR':directory}):
            plan=m.build_plan('desktop',[],{},set(),set(),set())
            path=Path(m.store_plan(plan));self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(m.consume_plan(path)['target'],'desktop');self.assertFalse(path.exists())
            with self.assertRaises(FileNotFoundError):m.consume_plan(path)
            plan['created']-=301;path=m.store_plan(plan)
            with self.assertRaises(ValueError):m.consume_plan(path)

    def test_pid_identity_change_aborts_without_signals(self):
        m=load();process=subprocess.Popen(['/bin/sleep','60'])
        try:
            record=m.process_record(Path('/proc')/str(process.pid));record['heroic_id']='test';record['start']-=1
            plan=m.build_plan('desktop',[record],{},set(),set(),set())
            with mock.patch.object(m,'request_window_close') as close:
                with self.assertRaises(ValueError):m.execute_plan(plan,inspect=lambda _:plan)
                close.assert_not_called()
            self.assertIsNone(process.poll())
        finally:process.terminate();process.wait()
