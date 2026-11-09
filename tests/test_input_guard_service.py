import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
import shutil
import subprocess
from unittest import mock

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

    def test_bluetooth_uhid_sources_are_corrected_but_virtual_usb_outputs_are_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            module = load()
            for number, identity, expected in (
                (1, '0005:0000054C:00000CE6', True),
                (2, '0003:0000054C:00000CE6', False),
                (3, '0005:0000045E:000002EA', False),
            ):
                device = root/'devices/virtual/misc/uhid'/str(number)
                device.mkdir(parents=True)
                (device/'uevent').write_text('HID_ID=' + identity + '\n')
                link = root/'class/hidraw'/f'hidraw{number}'/'device'
                link.parent.mkdir(parents=True)
                link.symlink_to(device)
                self.assertEqual(module.physical_node(f'hidraw{number}', root), expected)

    def test_bluetooth_rule_correction_and_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            guard, rules, state, refresh = self.fixture(folder)
            text = TEXT.replace('0003:054C:0CE6.000D', '0005:054C:0CE6.000D')
            path = rules/RULE
            path.write_text(text)
            guard.scan_once()
            self.assertIn('SUBSYSTEM=="hidraw"', path.read_text())
            self.assertEqual(refresh, [{'hidraw1'}])
            guard.restore()
            self.assertEqual(path.read_text(), text)


class SourceReservationTest(unittest.TestCase):
    def reservation(self,folder,refresh=None):
        guard,rules,state,_=GuardTest.fixture(self,folder)
        return load().SourceReservation(guard,refresh=refresh or (lambda:None))

    def test_rule_is_present_before_refresh_and_removed_before_access_is_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            reservation=self.reservation(folder)
            seen=[]
            reservation.refresh=lambda:seen.append(reservation.path.exists())
            reservation.install()
            self.assertEqual(reservation.path.read_text(),load().SOURCE_RULE)
            self.assertEqual(reservation.path.stat().st_mode & 0o777,0o644)
            reservation.restore()
            reservation.restore()
            self.assertEqual(seen,[True,False])
            self.assertFalse(reservation.journal.exists())

    def test_failed_install_refresh_can_be_recovered_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            reservation=self.reservation(folder,refresh=mock.Mock(side_effect=RuntimeError('udev failed')))
            with self.assertRaises(RuntimeError):reservation.install()
            self.assertTrue(reservation.path.exists())
            restarted=load().SourceReservation(reservation.guard,refresh=mock.Mock())
            restarted.install()
            restarted.refresh.assert_called_once()
            restarted.restore()
            self.assertFalse(restarted.journal.exists())

    def test_failed_restore_refresh_retains_journal_for_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            reservation=self.reservation(folder)
            reservation.install()
            reservation.refresh=mock.Mock(side_effect=RuntimeError('udev failed'))
            with self.assertRaises(RuntimeError):reservation.restore()
            self.assertFalse(reservation.path.exists())
            self.assertTrue(reservation.journal.exists())
            restarted=load().SourceReservation(reservation.guard,refresh=lambda:None)
            restarted.restore()
            self.assertFalse(restarted.journal.exists())

    def test_foreign_rule_is_never_adopted_without_a_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            reservation=self.reservation(folder)
            reservation.path.write_text(load().SOURCE_RULE)
            with self.assertRaises(ValueError):reservation.install()
            self.assertFalse(reservation.journal.exists())

    def test_edited_or_replaced_rule_is_preserved_with_recovery_record(self):
        for change in ('edit','replace','symlink','permissions'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                reservation=self.reservation(folder)
                reservation.install()
                if change=='edit':reservation.path.write_text('# external rule\n')
                elif change=='permissions':reservation.path.chmod(0o666)
                else:
                    replacement=Path(folder)/'external'
                    replacement.write_text(load().SOURCE_RULE)
                    reservation.path.unlink()
                    if change=='replace':replacement.replace(reservation.path)
                    else:reservation.path.symlink_to(replacement)
                with self.assertRaises((ValueError,OSError)):reservation.restore()
                self.assertTrue(reservation.journal.exists())
                self.assertTrue(reservation.path.exists())

    def test_complete_rule_created_before_interrupted_journal_commit_is_recovered(self):
        with tempfile.TemporaryDirectory() as folder:
            reservation=self.reservation(folder)
            module=load()
            module.atomic_json(reservation.journal,{'version':1,'fingerprint':None})
            reservation.path.write_text(module.SOURCE_RULE)
            restarted=module.SourceReservation(reservation.guard,refresh=lambda:None)
            restarted.install()
            restarted.restore()
            self.assertFalse(restarted.path.exists())

    def test_refresh_selects_supported_physical_nodes_and_siblings_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            expected=[]
            for number,location,identity,supported in (
                (1,'pci/usb','0003:0000054C:00000CE6',True),
                (2,'virtual/misc/uhid','0005:0000054C:00000CE6',True),
                (3,'virtual/misc/uhid','0003:0000054C:00000CE6',False),
                (4,'pci/usb','0003:0000045E:000002EA',False),
            ):
                device=root/'devices'/location/str(number)
                device.mkdir(parents=True)
                (device/'uevent').write_text('HID_ID='+identity+'\n')
                for subsystem,name in (('hidraw',f'hidraw{number}'),('input',f'event{number}'),
                                       ('input',f'js{number}'),('input',f'mouse{number}')):
                    entry=root/'class'/subsystem/name
                    entry.mkdir(parents=True)
                    (entry/'device').symlink_to(device)
                    if supported:expected.append(str(entry))
            self.assertEqual(set(load().supported_source_paths(root)),set(expected))

    @unittest.skipUnless(shutil.which('udevadm'),'udevadm unavailable')
    def test_source_rule_passes_real_udev_parser(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/load().SOURCE_RULE_NAME
            path.write_text(load().SOURCE_RULE)
            result=subprocess.run(['udevadm','verify',str(path)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_ready_is_published_after_reservation_and_stop_restores_access(self):
        self.run_main(fail_refresh=False)

    def test_failed_reservation_never_publishes_ready_and_retains_recovery(self):
        self.run_main(fail_refresh=True)

    def run_main(self,fail_refresh):
        import signal
        import stat
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            module=load()
            reservation=self.reservation(folder)
            runtime=reservation.guard.state
            root_runtime=mock.MagicMock(wraps=runtime)
            root_runtime.__truediv__.side_effect=lambda name:runtime/name
            root_runtime.lstat.return_value=SimpleNamespace(st_uid=0,st_mode=stat.S_IFDIR|0o755)
            handlers={}
            messages=[]
            def notify(message):
                messages.append(message)
                if message.startswith('READY='):
                    self.assertTrue(reservation.path.exists())
                    self.assertTrue(reservation.journal.exists())
                    handlers[signal.SIGTERM]()
                return True
            if fail_refresh:reservation.refresh=mock.Mock(side_effect=RuntimeError('udev failed'))
            with mock.patch.object(module,'RUNTIME',root_runtime), \
                 mock.patch.object(module.os,'geteuid',return_value=0), \
                 mock.patch.object(module.os,'umask'), \
                 mock.patch.object(module,'legacy_active',return_value=False), \
                 mock.patch.object(module,'RuleGuard',return_value=reservation.guard), \
                 mock.patch.object(module,'SourceReservation',return_value=reservation), \
                 mock.patch.object(module,'notify',side_effect=notify), \
                 mock.patch.object(module.signal,'signal',side_effect=lambda sig,handler:handlers.update({sig:handler})):
                if fail_refresh:
                    with self.assertRaisesRegex(RuntimeError,'udev failed'):module.main()
                else:module.main()
            self.assertFalse((runtime/'active').exists())
            self.assertEqual(reservation.path.exists(),fail_refresh)
            self.assertEqual(reservation.journal.exists(),fail_refresh)
            self.assertEqual(any(m.startswith('READY=') for m in messages),not fail_refresh)
