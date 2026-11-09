"""Fixed Go S mapping leases, source boundaries, and privileged rollback."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('desktop_mapping_guard', ROOT/'scripts/session-switch-input-guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
PATH = '/org/shadowblip/InputPlumber/CompositeDevice0'
ORIGINAL = '''version: 1
kind: DeviceProfile
name: Default
mapping:
- name: Custom right stick
  source_event:
    gamepad:
      axis:
        name: RightStick
  target_events:
  - gamepad:
      axis:
        name: RightStick
'''


class FakeBus:
    def __init__(self):
        self.current = ORIGINAL
        self.loads = []
        self.profile_path = ''
        self.exists = True
        self.sources = ['', '/dev/hidraw1']

    def __call__(self, path, operation, *args):
        if operation == 'exists':
            return self.exists
        if operation == 'GetProfileYaml':
            return self.current
        if operation == 'get:SourceDevicePaths':
            return self.sources
        if operation == 'get:ProfilePath':
            return self.profile_path
        if operation == 'LoadProfileFromYaml':
            self.loads.append(args[1])
            self.current = yaml.safe_dump(yaml.safe_load(args[1]), sort_keys=False)
            return
        raise AssertionError(operation)


class DesktopInputMappingTest(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        rule_guard = guard.RuleGuard(root/'rules', root/'state', owner_uid=os.getuid())
        bus = FakeBus()
        bridge = guard.DesktopProfileBridge(rule_guard, bus=bus, active_uid=os.getuid)
        return bridge, bus

    def test_mapping_consumes_left_controls_and_preserves_mouse_mappings(self):
        profile = guard.desktop_navigation_profile(ORIGINAL)
        self.assertNotIn('target_devices', profile)
        self.assertEqual(profile['mapping'][0], yaml.safe_load(ORIGINAL)['mapping'][0])
        consumed = [item['source_event']['gamepad'] for item in profile['mapping'][1:]]
        self.assertIn({'axis': {'name': 'LeftStick'}}, consumed)
        self.assertEqual({item['button'] for item in consumed if 'button' in item}, set(guard.NAV_BUTTONS))
        self.assertFalse(any(item.get('button') in ('LeftTrigger', 'RightTrigger', 'RightStick') for item in consumed))
        self.assertTrue(all('dbus' in event for item in profile['mapping'][1:] for event in item['target_events']))

    def test_existing_left_mapping_is_replaced_without_duplicate_forwarding(self):
        profile = yaml.safe_load(ORIGINAL)
        profile['mapping'].append({'name': 'old left', 'source_event': {'gamepad': {'axis': {'name': 'LeftStick'}}}, 'target_events': [{'keyboard': 'KeyA'}]})
        result = guard.desktop_navigation_profile(yaml.safe_dump(profile))
        self.assertNotIn('old left', [item['name'] for item in result['mapping']])
        for targets in ([], ['xbox-elite']):
            profile['target_devices'] = targets
            with self.assertRaises(ValueError):
                guard.desktop_navigation_profile(yaml.safe_dump(profile))

    def test_baseline_reset_reestablishes_only_the_owned_navigation_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            with patch.object(guard, 'desktop_map_sources', return_value=True):
                bridge.apply(PATH)
                applied = yaml.safe_load(bus.current)
                bus.current = ORIGINAL
                self.assertTrue(bridge.check(PATH))
                self.assertEqual(yaml.safe_load(bus.current), applied)
                loads = len(bus.loads)
                self.assertFalse(bridge.check(PATH))
                self.assertEqual(len(bus.loads), loads)
            bridge.restore_all()
            self.assertEqual(yaml.safe_load(bus.current), yaml.safe_load(ORIGINAL))

    def test_check_preserves_distinct_edits_and_ownership_changes(self):
        for change in ('profile', 'source', 'file'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                bridge, bus = self.fixture(directory)
                with patch.object(guard, 'desktop_map_sources', return_value=True):
                    bridge.apply(PATH)
                    if change == 'profile':
                        data = yaml.safe_load(bus.current)
                        data['mapping'][0]['name'] = 'External edit with same profile name'
                        bus.current = yaml.safe_dump(data)
                    elif change == 'source':
                        bus.sources = ['/dev/hidraw99']
                    else:
                        bus.profile_path = '/user/custom.yaml'
                    loads = len(bus.loads)
                    with self.assertRaises(ValueError):
                        bridge.check(PATH)
                    self.assertEqual(len(bus.loads), loads)
                    self.assertTrue(bridge.journal.exists())
                    bridge.disconnect()
                    self.assertEqual(len(bus.loads), loads)
                    self.assertTrue(bridge.journal.exists())

    def test_disconnect_preserves_external_profile_without_stopping_guard_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            bridge.start()
            try:
                with patch.object(guard, 'desktop_map_sources', return_value=True):
                    bridge.apply(PATH)
                bus.current = ORIGINAL.replace('Default', 'External edit')
                bridge.disconnect()
                self.assertTrue(bridge.journal.exists())
                self.assertGreaterEqual(bridge.server.fileno(), 0)
                self.assertIn('External edit', bus.current)
            finally:
                bridge.close()

    def test_socket_check_recovers_baseline_and_rejects_seat_change(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            bridge.start()
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.connect(str(bridge.path)); bridge.poll(0)
                with patch.object(guard, 'desktop_map_sources', return_value=True):
                    client.sendall(json.dumps({'open': PATH}).encode()+b'\n'); bridge.poll(0)
                    self.assertEqual(json.loads(client.recv(4096)), {'ok': True})
                    bus.current = ORIGINAL
                    client.sendall(b'{"check":true}\n'); bridge.poll(0)
                    self.assertEqual(json.loads(client.recv(4096)), {'ok': True, 'repaired': True})
                    bridge.active_uid = lambda: os.getuid() + 1
                    client.sendall(b'{"check":true}\n'); bridge.poll(0)
                    self.assertIn('seat ownership changed', json.loads(client.recv(4096))['error'])
                self.assertIsNone(bridge.client)
                self.assertEqual(yaml.safe_load(bus.current), yaml.safe_load(ORIGINAL))
            finally:
                client.close(); bridge.close()

    def test_apply_journals_before_write_and_repeat_close_restores_original(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            original_bus = bridge.bus
            def verify(path, op, *args):
                if op == 'LoadProfileFromYaml':
                    self.assertTrue(bridge.journal.exists())
                return original_bus(path, op, *args)
            bridge.bus = verify
            with patch.object(guard, 'desktop_map_sources', return_value=True):
                bridge.apply(PATH)
            self.assertEqual(bridge.journal.stat().st_mode & 0o777, 0o600)
            bridge.restore_all()
            bridge.restore_all()
            self.assertEqual(yaml.safe_load(bus.current), yaml.safe_load(ORIGINAL))
            self.assertFalse(bridge.journal.exists())

    def test_restart_recovers_profile_after_client_or_guard_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            with patch.object(guard, 'desktop_map_sources', return_value=True):
                bridge.apply(PATH)
            recovered = guard.DesktopProfileBridge(bridge.guard, bus=bus)
            self.assertEqual(recovered.records, {})
            self.assertEqual(yaml.safe_load(bus.current), yaml.safe_load(ORIGINAL))

    def test_external_profile_change_is_preserved_with_recovery_record(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            with patch.object(guard, 'desktop_map_sources', return_value=True):
                bridge.apply(PATH)
            bus.current = ORIGINAL.replace('Default', 'External edit')
            with self.assertRaises(ValueError):
                bridge.restore_all()
            self.assertIn('External edit', bus.current)
            self.assertTrue(bridge.journal.exists())

    def test_unknown_sources_paths_and_file_profiles_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            with patch.object(guard, 'desktop_map_sources', return_value=False):
                with self.assertRaises(ValueError):bridge.apply(PATH)
            with self.assertRaises(ValueError):bridge.apply('/unrelated')
            bus.profile_path = '/user/custom.yaml'
            with patch.object(guard, 'desktop_map_sources', return_value=True):
                with self.assertRaises(ValueError):bridge.apply(PATH)
            self.assertEqual(bus.loads, [])

    def test_socket_eof_restores_and_rejects_caller_supplied_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            bridge.start()
            try:
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.connect(str(bridge.path));bridge.poll(0)
                with patch.object(guard, 'desktop_map_sources', return_value=True):
                    client.sendall(json.dumps({'open': PATH}).encode()+b'\n');bridge.poll(0)
                self.assertEqual(json.loads(client.recv(4096)), {'ok': True})
                client.close();bridge.poll(0)
                self.assertEqual(yaml.safe_load(bus.current), yaml.safe_load(ORIGINAL))
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.connect(str(bridge.path));bridge.poll(0)
                client.sendall(json.dumps({'open': PATH, 'yaml': 'injected'}).encode()+b'\n');bridge.poll(0)
                self.assertIn('error', json.loads(client.recv(4096)))
                client.close()
            finally:
                bridge.close()
            self.assertFalse(bridge.path.exists())

    def test_foreign_uid_is_rejected_before_any_profile_change(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            bridge.active_uid = lambda: os.getuid()+1
            bridge.start()
            try:
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.connect(str(bridge.path));bridge.poll(0)
                self.assertEqual(client.recv(4096), b'')
                client.close()
                self.assertEqual(bus.loads, [])
            finally:bridge.close()


    def test_disappeared_composite_does_not_block_guard_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge, bus = self.fixture(directory)
            with patch.object(guard, 'desktop_map_sources', return_value=True):
                bridge.apply(PATH)
            loads = len(bus.loads)
            bus.exists = False
            bridge.restore_all()
            self.assertFalse(bridge.journal.exists())
            self.assertEqual(len(bus.loads), loads)
