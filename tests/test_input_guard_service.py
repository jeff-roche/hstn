import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/session-switch-input-guard.py'
RULE='50-inputplumber-hide-hidraw1-early.rules'
TEXT='ACTION=="add|change", SUBSYSTEMS=="hidraw", KERNEL=="hidraw1", KERNELS=="0003:054C:0CE6.000D", GOTO="valid"\n'

def load():
    spec=importlib.util.spec_from_file_location('input_guard',SCRIPT)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class GuardTest(unittest.TestCase):
    def fixture(self,folder):
        m=load();rules=Path(folder)/'rules';state=Path(folder)/'state';rules.mkdir();state.mkdir()
        refresh=[];guard=m.RuleGuard(rules,state,physical=lambda _:True,
                                    refresh=lambda nodes:refresh.append(set(nodes)),owner_uid=os.getuid())
        return guard,rules,state,refresh
    def test_patch_is_idempotent_and_persists_backup_for_restart(self):
        with tempfile.TemporaryDirectory() as d:
            guard,rules,state,refresh=self.fixture(d);path=rules/RULE;path.write_text(TEXT)
            guard.scan_once();self.assertIn('SUBSYSTEM=="hidraw"',path.read_text())
            guard.scan_once();self.assertEqual(refresh,[{'hidraw1'}])
            restarted=load().RuleGuard(rules,state,physical=lambda _:True,
                refresh=lambda nodes:refresh.append(set(nodes)),owner_uid=os.getuid())
            restarted.restore();self.assertEqual(path.read_text(),TEXT)
    def test_watches_a_second_session_and_regenerated_rule(self):
        with tempfile.TemporaryDirectory() as d:
            guard,rules,_,refresh=self.fixture(d);path=rules/RULE;path.write_text(TEXT)
            guard.scan_once();path.unlink();guard.scan_once()
            path.write_text(TEXT.replace('000D','000E'));guard.scan_once()
            guard.restore();self.assertIn('000E',path.read_text());self.assertEqual(len(refresh),3)
    def test_does_not_restore_another_writers_changes(self):
        with tempfile.TemporaryDirectory() as d:
            guard,rules,_,_=self.fixture(d);path=rules/RULE;path.write_text(TEXT)
            guard.scan_once();path.write_text('# external replacement\n');guard.restore()
            self.assertEqual(path.read_text(),'# external replacement\n')
    def test_upstream_corrected_rules_and_virtual_nodes_are_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            guard,rules,_,refresh=self.fixture(d);path=rules/RULE;fixed=TEXT.replace('SUBSYSTEMS','SUBSYSTEM')
            path.write_text(fixed);guard.scan_once();self.assertEqual(refresh,[])
            path.write_text(TEXT);guard.physical=lambda _:False;guard.scan_once()
            self.assertEqual(path.read_text(),TEXT);self.assertEqual(refresh,[])
    def test_symlinks_and_writable_rules_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            guard,rules,_,_=self.fixture(d);other=Path(d)/'other';other.write_text(TEXT)
            path=rules/RULE;path.symlink_to(other)
            with self.assertRaises((OSError,ValueError)):guard.scan_once()
            self.assertEqual(other.read_text(),TEXT)
            path.unlink();path.write_text(TEXT);path.chmod(0o666)
            with self.assertRaises(ValueError):guard.scan_once()
    def test_replaced_inode_is_not_restored_even_when_text_matches(self):
        with tempfile.TemporaryDirectory() as d:
            guard,rules,_,_=self.fixture(d);path=rules/RULE;path.write_text(TEXT);guard.scan_once()
            fixed=path.read_text();new=rules/'pending';new.write_text(fixed);new.replace(path)
            guard.restore();self.assertEqual(path.read_text(),fixed)

    def test_failed_udev_refresh_is_retried_after_process_restart(self):
        with tempfile.TemporaryDirectory() as d:
            guard,rules,state,_=self.fixture(d);path=rules/RULE;path.write_text(TEXT)
            def fail(_):raise RuntimeError('udev unavailable')
            guard.refresh=fail
            with self.assertRaises(RuntimeError):guard.scan_once()
            self.assertIn('SUBSYSTEM=="hidraw"',path.read_text())
            retried=[]
            restarted=load().RuleGuard(rules,state,physical=lambda _:True,
                refresh=lambda nodes:retried.append(set(nodes)),owner_uid=os.getuid())
            restarted.scan_once();self.assertEqual(retried,[{'hidraw1'}])
            restarted.scan_once();self.assertEqual(len(retried),1)

    def test_systemd_ready_notification_uses_notify_socket(self):
        import socket
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'notify')
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as receiver:
                receiver.bind(path);receiver.settimeout(1)
                with mock.patch.dict(os.environ,{'NOTIFY_SOCKET':path}):
                    self.assertTrue(load().notify('READY=1'))
                self.assertEqual(receiver.recv(128),b'READY=1')
