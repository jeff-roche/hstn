import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/session-transition-guard.py'

def load():
 spec=importlib.util.spec_from_file_location('transition_guard',SCRIPT)
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class TransitionGuardTest(unittest.TestCase):
 def test_ready_service_protects_only_lid_events_and_expires(self):
  m=load()
  with mock.patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
   self.assertEqual(m.start(),0)
  args=run.call_args.args[0]
  self.assertIn('--user',args);self.assertIn('--collect',args)
  self.assertIn('--service-type=notify',args)
  self.assertIn('--property=RuntimeMaxSec=40s',args)
  self.assertIn('--property=TimeoutStartSec=5s',args)
  self.assertIn('--property=NotifyAccess=all',args)
  self.assertEqual(args[-1],'--inhibit')

 def test_inhibitor_preserves_readiness_address_for_its_child(self):
  m=load()
  with mock.patch.dict(os.environ,{'NOTIFY_SOCKET':'/private/notify'}),mock.patch.object(m.os,'execve') as execute:
   m.inhibit()
  program,args,environment=execute.call_args.args
  self.assertEqual(program,'/usr/bin/systemd-inhibit')
  self.assertIn('--what=handle-lid-switch',args)
  self.assertNotIn('--what=sleep',args)
  self.assertEqual(args[-3:],['--hold','--seconds','30'])
  self.assertEqual(environment['HSTN_TRANSITION_NOTIFY_SOCKET'],'/private/notify')

 def test_holder_notifies_before_exit_and_has_bounded_lifetime(self):
  self.assertTrue(SCRIPT.exists())
  with tempfile.TemporaryDirectory() as folder:
   path=str(Path(folder)/'notify')
   with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as receiver:
    receiver.bind(path);receiver.settimeout(3)
    child=subprocess.Popen(['/usr/bin/python3','-B',str(SCRIPT),'--hold','--seconds','1'],env=dict(os.environ,NOTIFY_SOCKET=path),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
     message=receiver.recv(4096)
     self.assertIn(b'READY=1',message);self.assertIsNone(child.poll())
     stdout,stderr=child.communicate(timeout=3)
     self.assertEqual(child.returncode,0,stderr)
    finally:
     if child.poll() is None:child.kill();child.communicate()

 def test_missing_notify_or_excessive_hold_time_fails(self):
  self.assertTrue(SCRIPT.exists())
  for arguments in (['--hold','--seconds','0'],['--hold','--seconds','31'],['--hold','--seconds','1']):
   env=dict(os.environ);env.pop('NOTIFY_SOCKET',None)
   result=subprocess.run(['/usr/bin/python3','-B',str(SCRIPT),*arguments],env=env,capture_output=True,timeout=3)
   self.assertNotEqual(result.returncode,0)
