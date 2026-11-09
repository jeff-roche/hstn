import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('supported_controllers_test', ROOT/'scripts/supported-controllers.py')
controllers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controllers)


class SupportedControllersTest(unittest.TestCase):
    def device(self, root, location, identity):
        device = root/'devices'/location
        device.mkdir(parents=True)
        (device/'uevent').write_text('HID_ID=' + identity + '\n')
        link = root/'class/hidraw/hidraw0/device'
        link.parent.mkdir(parents=True)
        link.symlink_to(device)
        return device

    def test_supported_usb_and_bluetooth_sources_enable_isolation(self):
        for location, identity, expected in (
            ('pci/usb/pad', '0003:0000054C:00000CE6', True),
            ('pci/usb/pad', '0003:0000045E:000002EA', False),
            ('bluetooth/pad', '0005:0000054C:00000CE6', True),
            ('virtual/misc/uhid/pad', '0005:0000054C:00000CE6', True),
            ('virtual/misc/uhid/pad', '0005:0000045E:000002EA', False),
            ('virtual/misc/uhid/pad', '0003:0000054C:00000CE6', False),
        ):
            with self.subTest(location=location, identity=identity), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.device(root, location, identity)
                self.assertEqual(controllers.connected(root), expected)

    def test_missing_or_disconnected_controller_does_not_enable_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertFalse(controllers.connected(root))
            device = self.device(root, 'pci/usb/pad', '0003:0000054C:00000CE6')
            (device/'uevent').unlink()
            self.assertFalse(controllers.connected(root))

    def test_supported_event_sibling_resolves_physical_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            device = self.device(root, 'pci/usb/pad', '0003:0000054C:00000CE6')
            event = device/'input/input1'
            event.mkdir(parents=True)
            link = root/'class/input/event1/device'
            link.parent.mkdir(parents=True)
            link.symlink_to(event)
            self.assertEqual(controllers.supported_parent('/dev/input/event1', root), str(device))

    def test_composites_with_unknown_sources_are_not_claimed(self):
        with patch.object(controllers, 'supported_parent', side_effect=lambda source: '/pad' if source == '/dev/hidraw1' else None):
            self.assertTrue(controllers.supported_sources(['/dev/hidraw1']))
            self.assertFalse(controllers.supported_sources(['/dev/hidraw1', '/dev/hidraw2']))
            self.assertFalse(controllers.supported_sources([]))

    def test_isolation_readiness_excludes_unrelated_controller_groups(self):
        physical = {'node': '/dev/hidraw1', 'virtual': False}
        virtual = {'node': '/dev/hidraw2', 'virtual': True,
                   'identity': {'HID_ID': '0003:0000054C:00000CE6'}}
        unrelated = {'node': '/dev/hidraw3', 'virtual': False}
        owned = {'SourceDevicePaths': ['/dev/hidraw1']}
        other = {'SourceDevicePaths': ['/dev/hidraw3']}
        report = {'routes': {'devices': [physical, virtual, unrelated], 'errors': ['inspection failed']},
                  'inputplumber': {'composites': [owned, other], 'errors': []}}
        with patch.object(controllers, 'supported_parent', side_effect=lambda source: '/pad' if source == '/dev/hidraw1' else None):
            scoped = controllers.isolation_report(report)
        self.assertEqual(scoped['routes']['devices'], [physical, virtual])
        self.assertEqual(scoped['inputplumber']['composites'], [owned])
        self.assertEqual(scoped['routes']['errors'], ['inspection failed'])
        self.assertEqual(len(report['routes']['devices']), 3)

    def test_bluetooth_uhid_event_sibling_resolves_source_not_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            device = self.device(root, 'virtual/misc/uhid/bluetooth', '0005:0000054C:00000CE6')
            event = device/'input/input1'
            event.mkdir(parents=True)
            (event/'uevent').write_text('PRODUCT=5/54c/ce6/100\n')
            link = root/'class/input/event1/device'
            link.parent.mkdir(parents=True)
            link.symlink_to(event)
            self.assertEqual(controllers.supported_parent('/dev/input/event1', root), str(device))

    def test_bluetooth_disconnect_and_reconnect_with_new_node(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            device = self.device(root, 'virtual/misc/uhid/bluetooth', '0005:0000054C:00000CE6')
            self.assertTrue(controllers.connected(root))
            (root/'class/hidraw/hidraw0/device').unlink()
            self.assertFalse(controllers.connected(root))
            link = root/'class/hidraw/hidraw8/device'
            link.parent.mkdir(parents=True)
            link.symlink_to(device)
            self.assertTrue(controllers.connected(root))
