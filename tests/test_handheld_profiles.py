"""Go S source boundaries, preserved routing, and reusable input presentation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


controllers = load('supported-controllers')
guard = load('session-switch-input-guard')
profiles = load('input-profiles')
outputs = load('controller-outputs')


class HandheldProfilesTest(unittest.TestCase):
    def host(self, root, model='83L3'):
        dmi = root/'class/dmi/id'
        dmi.mkdir(parents=True)
        (dmi/'sys_vendor').write_text('LENOVO\n')
        (dmi/'product_name').write_text(model+'\n')

    def test_dmi_and_transport_boundaries_match_standalone_guard(self):
        for model in (*controllers.LEGION_GO_S_MODELS, '83E1'):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.host(root, model)
                for product in ('E310', 'E311'):
                    identity = {'HID_ID': f'0003:00001A86:0000{product}'}
                    for module in (controllers, guard):
                        self.assertEqual(module.source_identity(identity, False, root), model != '83E1')
                        self.assertFalse(module.source_identity(identity, True, root))
                        self.assertFalse(module.source_identity({'HID_ID': '0005:00001A86:0000E310'}, False, root))

    def test_hid_evdev_and_led_composite_membership(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.host(root)
            hid = root/'devices/pci/usb/pad'
            hid.mkdir(parents=True)
            (hid/'uevent').write_text('HID_ID=0003:00001A86:0000E310\n')
            for kind, node in (('hidraw', 'hidraw0'), ('input', 'event0')):
                entry = root/'class'/kind/node
                entry.mkdir(parents=True)
                (entry/'device').symlink_to(hid)
                for module in (controllers, guard):
                    self.assertEqual(module.supported_parent(node, root), str(hid))
            led = root/'class/leds/go_s:rgb:joystick_rings'
            led.mkdir(parents=True)
            (led/'device').symlink_to(hid)
            self.assertEqual(controllers.supported_parent(led, root), str(hid))
            self.assertIsNone(controllers.supported_parent('/dev/hidraw99', root))

    def test_unknown_and_mixed_composites_are_refused(self):
        gos = {'profile': 'legion-go-s', 'output': 'preserve'}
        xbox = {'output': 'xbox-series'}
        for values, expected in (([gos, gos], 'legion-go-s'), ([gos, None], None), ([gos, xbox], None), ([], None)):
            with patch.object(controllers, 'profile_for', side_effect=values):
                self.assertEqual(controllers.composite_profile(list(range(len(values)))), expected)

    def test_preserved_output_never_enters_replacement_managers(self):
        set_targets = Mock()
        manager = outputs.ControllerOutputs(set_targets)
        manager.sony = Mock(ready_paths=set(), companions=set(), failures={}, controllers={})
        manager.xbox = Mock(ready_paths=set(), companions=set(), failures={}, controllers={})
        record = {'path': '/gos', 'sources': ['/dev/hidraw0'], 'targets': ['xbox-elite', 'keyboard', 'mouse'], 'owned': False}
        with patch.object(outputs.controllers, 'supported_sources', return_value=True), patch.object(outputs.controllers, 'composite_profile', return_value='legion-go-s'):
            manager.update([record])
        manager.sony.update.assert_called_once_with([])
        manager.xbox.update.assert_called_once_with([])
        set_targets.assert_not_called()

    def test_handheld_actions_and_glyphs_are_independent_of_output(self):
        profile = profiles.PROFILES['legion-go-s']
        self.assertEqual(profile['output_policy'], 'preserve')
        self.assertEqual(profile['activation'], ('Gamepad:Button:Guide', 'Gamepad:Button:QuickAccess'))
        self.assertEqual(profiles.action('ui_accept', 'legion-go-s'), 'ui_accept')
        self.assertIsNone(profiles.action('ui_guide', 'legion-go-s'))
        for asset in profiles.PROMPTS[profile['glyphs']][0]:
            self.assertTrue((ROOT/'assets/controller'/f'{asset}.svg').exists())


    def test_empty_led_path_requires_verified_go_s_inputs_and_led(self):
        gos = {'profile': 'legion-go-s'}
        with patch.object(controllers, 'legion_go_s_host', return_value=True), \
             patch.object(controllers, 'profile_for', return_value=gos), \
             patch.object(controllers.Path, 'exists', return_value=True):
            self.assertEqual(controllers.composite_sources(['', '/dev/hidraw1']),
                             ['/sys/class/leds/go_s:rgb:joystick_rings', '/dev/hidraw1'])
            for sources in ([''], ['', '', '/dev/hidraw1'], ['', '/sys/class/leds/go_s:rgb:joystick_rings']):
                self.assertEqual(controllers.composite_sources(sources), [])
            with patch.object(controllers, 'legion_go_s_host', return_value=False):
                self.assertEqual(controllers.composite_sources(['', '/dev/hidraw1']), [])
            with patch.object(controllers.Path, 'exists', return_value=False):
                self.assertEqual(controllers.composite_sources(['', '/dev/hidraw1']), [])
            with patch.object(controllers, 'profile_for', return_value=None):
                self.assertEqual(controllers.composite_sources(['', '/dev/hidraw1']), [])


    def test_native_deck_outputs_are_recognized_without_accepting_physical_or_steam_secondary_devices(self):
        for identity, expected in (
                ('0003:000028DE:000012FF', True),
                ('0003:000028DE:00001205', True),
                ('0003:0000045E:00000B00', True),
                ('0003:000028DE:000011FF', False),
                ('0003:000028DE:00009999', False)):
            with self.subTest(identity=identity):
                device = {'virtual': True, 'identity': {'HID_ID': identity}}
                self.assertEqual(controllers.handheld_output(device), expected)
                device['virtual'] = False
                self.assertFalse(controllers.handheld_output(device))

    def test_readiness_scope_keeps_the_native_go_s_route(self):
        devices = [
            {'node': '/dev/hidraw8', 'virtual': True, 'identity': {'HID_ID': '0003:000028DE:000012FF'}},
            {'node': '/dev/input/event21', 'virtual': True, 'identity': {'HID_ID': '0003:000028DE:000011FF'}},
        ]
        report = {'routes': {'devices': devices, 'errors': []},
                  'inputplumber': {'composites': [{'SourceDevicePaths': ['/dev/hidraw1']}]}}
        with patch.object(controllers, 'supported_parent', return_value=None), \
             patch.object(controllers, 'supported_sources', return_value=True):
            scoped = controllers.isolation_report(report)
        self.assertEqual([device['node'] for device in scoped['routes']['devices']], ['/dev/hidraw8'])
