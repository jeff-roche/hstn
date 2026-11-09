import copy
import importlib.util
from pathlib import Path
import unittest
import contextlib
import io
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/controller-route-snapshot.py'
spec = importlib.util.spec_from_file_location('routes', SCRIPT)
routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routes)

class IsolationTest(unittest.TestCase):
    def baseline(self):
        return {'routes': {'errors': [], 'devices': [
            {'node': '/dev/hidraw1', 'virtual': False, 'readable_now': False, 'steam_holders': []},
            {'node': '/dev/hidraw13', 'virtual': True, 'readable_now': True, 'steam_holders': []}]},
            'inputplumber': {'errors': [], 'composites': [
                {'SourceDevicePaths': ['/dev/hidraw1'], 'InterceptMode': 1,
                 'DbusDevices': ['/target/dbus0'], 'TargetDevices': ['/target/gamepad0']} ]}}

    def test_ready_only_after_physical_source_is_hidden(self):
        report = self.baseline()
        self.assertEqual(routes.isolation_issues(report), [])
        report['routes']['devices'][0]['readable_now'] = True
        self.assertTrue(any('readable' in issue for issue in routes.isolation_issues(report)))

    def test_permission_revocation_does_not_fix_existing_descriptor(self):
        report = self.baseline()
        report['routes']['devices'][0]['steam_holders'] = [{'pid': 42, 'fd': '5'}]
        self.assertTrue(any('Steam' in issue for issue in routes.isolation_issues(report)))

    def test_incomplete_discovery_or_inspection_never_passes(self):
        for field, value in [('composites', []), ('errors', ['timeout'])]:
            report = self.baseline()
            report['inputplumber'][field] = value
            self.assertTrue(routes.isolation_issues(report))
        report = self.baseline()
        report['routes']['devices'].pop(0)
        self.assertTrue(routes.isolation_issues(report))

    def test_virtual_route_and_interception_are_required(self):
        report = self.baseline()
        report['routes']['devices'].pop()
        self.assertTrue(routes.isolation_issues(report))
        report = self.baseline()
        report['inputplumber']['composites'][0]['InterceptMode'] = 0
        self.assertTrue(routes.isolation_issues(report))

    def playstation_report(self):
        report=self.baseline()
        root='/sys/devices/pci/controller'
        report['routes']['devices'][0].update(sysfs=root,identity={'HID_ID':'0003:0000054C:00000CE6'})
        report['routes']['devices'][1].update(sysfs='/sys/devices/virtual/misc/uhid/pad',identity={'HID_ID':'0003:0000054C:00000CE6'})
        report['routes']['devices'].append({'node':'/dev/input/event17','virtual':False,
            'sysfs':root+'/input/input36','identity':{},'readable_now':False,'steam_holders':[]})
        report['inputplumber']['composites'][0]['path']='/primary'
        report['inputplumber']['composites'].append({'path':'/suppressed',
            'SourceDevicePaths':['/dev/input/event17'],'InterceptMode':1,
            'DbusDevices':['/target/dbus1'],'TargetDevices':[]})
        return report

    def test_single_pad_allows_disabled_sibling_only_with_ready_primary(self):
        report=self.playstation_report()
        self.assertTrue(routes.isolation_issues(report))
        self.assertEqual(routes.isolation_issues(report,single_playstation=True),[])
        report['inputplumber']['composites'][0]['TargetDevices']=[]
        self.assertTrue(routes.isolation_issues(report,single_playstation=True))

    def test_single_pad_never_exempts_unrelated_or_readable_sources(self):
        report=self.playstation_report()
        report['routes']['devices'][2]['sysfs']='/sys/devices/other/input/input36'
        self.assertTrue(routes.isolation_issues(report,single_playstation=True))
        report=self.playstation_report();report['routes']['devices'][2]['readable_now']=True
        self.assertTrue(routes.isolation_issues(report,single_playstation=True))

    def test_duplicate_virtual_playstation_outputs_still_block(self):
        report=self.playstation_report()
        report['routes']['devices'].append(dict(report['routes']['devices'][1],node='/dev/hidraw14'))
        self.assertTrue(routes.isolation_issues(report,single_playstation=True))

    def test_cli_single_output_gate_accepts_only_safely_suppressed_siblings(self):
        report=self.playstation_report()
        with mock.patch.object(routes,'device_routes',return_value=report['routes']),mock.patch.object(routes,'inputplumber_state',return_value=report['inputplumber']),mock.patch('sys.argv',['routes','--check-isolation','--single-playstation']),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(routes.main(),0)
            self.assertIn('"isolation_issues": []',output.getvalue())

    def test_multiple_controllers_require_one_output_each(self):
        report = self.playstation_report()
        physical = dict(report['routes']['devices'][0], node='/dev/hidraw2', sysfs='/sys/devices/pci/second')
        virtual = dict(report['routes']['devices'][1], node='/dev/hidraw15', sysfs='/sys/devices/virtual/misc/uhid/second')
        report['routes']['devices'].extend([physical, virtual])
        report['inputplumber']['composites'].append({
            'path': '/second', 'SourceDevicePaths': ['/dev/hidraw2'], 'InterceptMode': 1,
            'DbusDevices': ['/target/dbus2'], 'TargetDevices': ['/target/gamepad2']})
        self.assertEqual(routes.isolation_issues(report, single_playstation=True), [])
        report['routes']['devices'].remove(virtual)
        self.assertTrue(routes.isolation_issues(report, single_playstation=True))

    def test_bluetooth_source_and_siblings_cannot_bypass_isolation(self):
        report = self.playstation_report()
        root = '/sys/devices/virtual/misc/uhid/bluetooth'
        source = report['routes']['devices'][0]
        source.update(sysfs=root, sysfs_virtual=True, identity={'HID_ID': '0005:0000054C:00000CE6'})
        report['routes']['devices'][2].update(sysfs=root+'/input/input36', sysfs_virtual=True)
        self.assertEqual(routes.isolation_issues(report, single_playstation=True), [])
        source['readable_now'] = True
        self.assertTrue(any('Physical source remains readable' in issue
                            for issue in routes.isolation_issues(report, single_playstation=True)))
        source['readable_now'] = False
        source['steam_holders'] = [{'pid': 42, 'fd': '5'}]
        self.assertTrue(any('Steam already holds' in issue
                            for issue in routes.isolation_issues(report, single_playstation=True)))

    def test_mixed_usb_and_bluetooth_controllers_need_independent_outputs(self):
        report = self.playstation_report()
        bluetooth = dict(report['routes']['devices'][0], node='/dev/hidraw3',
                         sysfs='/sys/devices/virtual/misc/uhid/bluetooth', sysfs_virtual=True,
                         identity={'HID_ID': '0005:0000054C:00000CE6'})
        output = dict(report['routes']['devices'][1], node='/dev/hidraw16')
        report['routes']['devices'].extend([bluetooth, output])
        report['inputplumber']['composites'].append({
            'path': '/bluetooth', 'SourceDevicePaths': ['/dev/hidraw3'], 'InterceptMode': 1,
            'DbusDevices': ['/target/dbus3'], 'TargetDevices': ['/target/gamepad3']})
        self.assertEqual(routes.isolation_issues(report, single_playstation=True), [])
        report['routes']['devices'].remove(output)
        self.assertTrue(routes.isolation_issues(report, single_playstation=True))
