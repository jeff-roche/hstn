"""Heroic gets one browser-readable gamepad, with journaled native restoration."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('handheld_output_test', ROOT/'scripts/handheld-session-output.py')
output = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(output)
PATH = '/org/shadowblip/InputPlumber/CompositeDevice0'


class Hardware:
    def __init__(self, root):
        self.root = root
        self.current = ['deck-uhid', 'keyboard', 'mouse']
        self.sources = ['', '/dev/hidraw1']
        self.mode = 0
        self.present = True
        self.calls = []
        self.now = 0
        self.bind = True

    def get(self, path, interface, name):
        if interface == output.TARGET and name == 'DeviceType':
            return path.rsplit('/', 1)[-1]
        if path == PATH and interface == output.COMPOSITE:
            if name == 'TargetDevices': return ['/target/'+kind for kind in self.current]
            if name == 'SourceDevicePaths': return list(self.sources)
            if name == 'InterceptMode': return self.mode
        raise AssertionError((path, interface, name))

    def set(self, path, targets):
        record = json.loads((self.root/output.JOURNAL).read_text())
        assert record['original'] == ['deck-uhid', 'keyboard', 'mouse']
        self.calls.append((path, list(targets)))
        if self.bind: self.current = list(targets)

    def sleep(self, duration):
        self.now += duration

    def lease(self):
        return output.OutputLease(self.root, get_property=self.get, set_targets=self.set,
            exists=lambda path: self.present, supported=lambda sources: sources == self.sources,
            clock=lambda: self.now, sleep=self.sleep)


class HandheldSessionOutputTest(unittest.TestCase):
    def test_native_deck_is_replaced_once_then_restored_after_owned_session(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder)); lease = hw.lease()
            lease.acquire(PATH, hw.sources)
            self.assertEqual(hw.current, ['xbox-elite', 'keyboard', 'mouse'])
            self.assertEqual(lease.path.stat().st_mode & 0o777, 0o600)
            lease.acquire(PATH, hw.sources)
            self.assertEqual(len(hw.calls), 1)
            hw.mode = 1
            hw.lease().recover(owned=True)  # Independent restore watchdog.
            self.assertEqual(hw.current, ['deck-uhid', 'keyboard', 'mouse'])
            self.assertFalse(lease.path.exists())
            lease.recover()
            self.assertEqual(len(hw.calls), 2)

    def test_existing_xbox_and_custom_outputs_are_preserved(self):
        for kinds in (['xbox-elite','keyboard','mouse'], ['deck-uhid','keyboard','mouse','touchscreen']):
            with self.subTest(kinds=kinds), tempfile.TemporaryDirectory() as folder:
                hw = Hardware(Path(folder)); hw.current = list(kinds); lease = hw.lease()
                lease.acquire(PATH, hw.sources)
                self.assertEqual(hw.current, kinds)
                self.assertEqual(hw.calls, [])
                self.assertFalse(lease.path.exists())

    def test_binding_timeout_retains_recovery_until_original_is_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder)); lease = hw.lease(); hw.bind = False
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                lease.acquire(PATH, hw.sources)
            self.assertTrue(lease.path.exists())
            lease.recover(owned=True)
            self.assertFalse(lease.path.exists())
            self.assertEqual(hw.current, ['deck-uhid','keyboard','mouse'])

    def test_recovery_preserves_external_outputs_sources_and_input_owners(self):
        for change in ('outputs','sources','owner'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                hw = Hardware(Path(folder)); lease = hw.lease(); lease.acquire(PATH, hw.sources)
                if change == 'outputs': hw.current = ['ds5','mouse','keyboard']
                elif change == 'sources': hw.sources = ['/dev/hidraw99']
                else: hw.mode = 2
                calls = len(hw.calls)
                with self.assertRaises(RuntimeError): hw.lease().recover()
                self.assertEqual(len(hw.calls), calls)
                self.assertTrue(lease.path.exists())

    def test_unplug_removes_only_obsolete_recovery_record(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder)); lease = hw.lease(); lease.acquire(PATH, hw.sources)
            hw.present = False
            lease.recover()
            self.assertFalse(lease.path.exists())
            self.assertEqual(len(hw.calls), 1)

    def test_idle_only_adoption_and_recovery_record_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder)); lease = hw.lease(); hw.mode = 1
            with self.assertRaises(RuntimeError): lease.acquire(PATH, hw.sources)
            self.assertFalse(lease.path.exists())
            hw.mode = 0; lease.acquire(PATH, hw.sources)
            lease.path.chmod(0o644)
            with self.assertRaises(RuntimeError): lease.recover()
            lease.path.chmod(0o600)
            record = json.loads(lease.path.read_text()); record['applied'] = ['arbitrary']
            lease.path.write_text(json.dumps(record))
            with self.assertRaises(RuntimeError): lease.recover()
            self.assertEqual(len(hw.calls), 1)

    def test_symlink_record_is_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            hw = Hardware(Path(folder)); lease = hw.lease()
            other = Path(folder)/'other'; other.write_text('untouched')
            lease.path.symlink_to(other)
            with self.assertRaises(OSError): lease.recover()
            self.assertEqual(other.read_text(), 'untouched')
