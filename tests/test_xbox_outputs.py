import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('controller_outputs_test', ROOT/'scripts/controller-outputs.py')
outputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(outputs)


class XboxOutputsTest(unittest.TestCase):
    def setUp(self):
        self.records = []
        self.nodes = {'sony': set(), 'xbox': set()}
        self.calls = []
        self.parents = {}

        def setter(path, targets):
            self.calls.append((path, targets))
            record = next(record for record in self.records if record['path'] == path)
            family = 'xbox' if path.startswith('/xbox') else 'sony'
            self.nodes[family].discard(path)
            record['targets'] = [] if targets == ['null'] else [path + '/target']
            if targets != ['null']:
                self.nodes[family].add(path)

        self.manager = outputs.ControllerOutputs(setter)
        for family, manager in (('sony', self.manager.sony), ('xbox', self.manager.xbox)):
            manager.parent_for = self.parents.get
            manager.required_for = lambda source: {source}
            manager.virtual_devices = lambda family=family: set(self.nodes[family])
            manager.device_ready = lambda node: True
        for name, value in (
            ('supported_sources', lambda sources: bool(sources) and all(source in self.parents for source in sources)),
            ('supported_parent', self.parents.get),
            ('xbox_source', lambda source: self.parents.get(source, '').startswith('/xbox'))):
            patch = mock.patch.object(outputs.controllers, name, side_effect=value)
            patch.start()
            self.addCleanup(patch.stop)

    def add(self, path, source, owned=True):
        self.parents[source] = path
        self.records.append({'path': path, 'sources': [source], 'targets': ['/default'], 'owned': owned})

    def settle(self):
        for _ in range(12):
            if self.manager.update(self.records):
                return
        self.fail(str(self.manager.failures))

    def test_input_only_xbox_and_dualsense_receive_separate_family_outputs(self):
        self.add('/xbox1', '/dev/input/event1')
        self.add('/sony1', '/dev/hidraw2')
        self.settle()
        self.assertIn(('/xbox1', ['xbox-series', 'mouse', 'keyboard']), self.calls)
        self.assertIn(('/sony1', ['ds5', 'mouse', 'keyboard']), self.calls)
        self.assertEqual(self.manager.ready_paths, {'/xbox1', '/sony1'})

    def test_two_xbox_reconnect_does_not_reset_other_controller(self):
        self.add('/xbox1', '/dev/input/event1')
        self.add('/xbox2', '/dev/hidraw2')
        self.settle()
        first = list(self.calls)
        self.records.pop(0)
        self.nodes['xbox'].discard('/xbox1')
        self.manager.update(self.records)
        self.assertEqual(self.manager.ready_paths, {'/xbox2'})
        self.add('/xbox1', '/dev/input/event7')
        self.settle()
        self.assertEqual([call for call in self.calls if call[0] == '/xbox2'],
                         [call for call in first if call[0] == '/xbox2'])

    def test_existing_owner_is_preserved_while_other_family_initializes(self):
        self.add('/xbox1', '/dev/input/event1', owned=False)
        self.add('/sony1', '/dev/hidraw2')
        for _ in range(6):
            self.manager.update(self.records)
        self.assertIn('/xbox1', self.manager.failures)
        self.assertEqual(self.manager.ready_paths, {'/sony1'})
        self.assertFalse(any(path == '/xbox1' for path, _ in self.calls))

    def test_virtual_xbox_output_is_discovered_without_hidraw(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index, location in enumerate(('virtual/input', 'pci/usb')):
                parent = root/'devices'/location/f'input{index}'
                parent.mkdir(parents=True)
                (parent/'uevent').write_text('PRODUCT=3/45e/b12/1\n')
                link = root/'class/input'/f'event{index}'/'device'
                link.parent.mkdir(parents=True)
                link.symlink_to(parent)
            self.assertEqual(outputs.xbox_devices(root), [str(root/'devices/virtual/input/input0')])

    def test_missing_output_times_out_without_creating_duplicate(self):
        self.add('/xbox1', '/dev/input/event1')
        self.manager.update(self.records)
        state = self.manager.xbox.controllers['/xbox1']
        state.clock = lambda: 100
        state.binding_started = 0
        state.max_binding_attempts = 1
        self.manager.xbox.device_ready = lambda node: False
        self.manager.update(self.records)
        self.assertIn('/xbox1', self.manager.failures)
        calls = list(self.calls)
        self.manager.update(self.records)
        self.assertEqual(self.calls, calls)

    def test_bluetooth_hid_primary_suppresses_evdev_sibling(self):
        self.add('/xbox1', '/dev/hidraw1')
        self.parents['/dev/input/event1'] = '/xbox1'
        self.records.append({'path': '/xbox-buttons', 'sources': ['/dev/input/event1'],
                             'targets': ['/default'], 'owned': True})
        self.settle()
        self.assertEqual(self.manager.companions, {'/xbox-buttons'})
        self.assertIn(('/xbox-buttons', ['null']), self.calls)
        self.assertFalse(any(path == '/xbox-buttons' and targets[0] != 'null'
                             for path, targets in self.calls))

    def test_bluetooth_hid_does_not_wait_for_optional_feedback_event_source(self):
        with mock.patch.object(outputs.controllers, 'supported_parent', return_value='/bluetooth'):
            self.assertEqual(outputs.xbox_required('/dev/hidraw3'), {'/dev/hidraw3'})
