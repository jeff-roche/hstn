import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/session-close.py'
def load():
    spec=importlib.util.spec_from_file_location('close_windows',SCRIPT)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class WindowOwnershipTest(unittest.TestCase):
    def run_close(self,owner,live_start=100):
        m=load();record={'pid':12345,'uid':m.os.getuid(),'start':100,'name':'game', 'namespace_pids':[12345,42]}
        tree=SimpleNamespace(stdout='  0x123 "Editor": () 800x600+0+0\n')
        props=SimpleNamespace(stdout='_NET_WM_PID(CARDINAL) = 42\nWM_CLASS = "Editor"\nWM_PROTOCOLS(ATOM) = WM_DELETE_WINDOW\n')
        with mock.patch.dict(m.os.environ,{'DISPLAY':':test'}), mock.patch.object(m.subprocess,'run',side_effect=[tree,props]), \
             mock.patch.object(m,'window_owners',return_value={0x123:owner}), \
             mock.patch.object(m,'process_record',return_value=dict(record,start=live_start)), mock.patch.object(m,'send_delete') as send:
            m.request_window_close([record]);return send.call_args_list
    def test_inner_pid_collision_never_closes_unrelated_window(self):
        self.assertEqual(self.run_close(99),[])
    def test_unknown_x_client_identity_is_not_a_pid_property_fallback(self):
        self.assertEqual(self.run_close(None),[])
    def test_verified_host_owner_can_receive_close(self):
        self.assertEqual(self.run_close(12345),[mock.call(0x123)])
    def test_reused_host_pid_never_receives_window_close(self):
        self.assertEqual(self.run_close(12345,live_start=101),[])
