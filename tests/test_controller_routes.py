import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/controller-route-snapshot.py'


class ControllerRoutesTest(unittest.TestCase):
    def test_distinguishes_physical_and_virtual_open_steam_devices(self):
        self.assertTrue(SCRIPT.exists(), 'Controller route probe missing')
        spec = importlib.util.spec_from_file_location('routes', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sysfs, proc, dev = (root / name for name in ('sys', 'proc', 'dev'))
            dev.mkdir()
            for name, location in (('hidraw1', 'pci/usb/controller'),
                                   ('hidraw13', 'virtual/misc/uhid/controller')):
                device = sysfs / 'devices' / location
                device.mkdir(parents=True)
                (device / 'uevent').write_text('HID_ID=0003:0000054C:00000CE6\nHID_NAME=DualSense\n')
                entry = sysfs / 'class/hidraw' / name
                entry.mkdir(parents=True)
                (entry / 'device').symlink_to(device)
                (dev / name).touch()
            for pid, command, nodes in ((123, 'steam', ['hidraw1', 'hidraw13']),
                                         (456, 'unrelated', ['hidraw1'])):
                process = proc / str(pid)
                (process / 'fd').mkdir(parents=True)
                (process / 'comm').write_text(command + '\n')
                for fd, name in enumerate(nodes):
                    (process / 'fd' / str(fd)).symlink_to(dev / name)
            report = module.device_routes(sysfs, proc, dev)
            self.assertEqual(report['errors'], [])
            routes = {Path(route['node']).name: route for route in report['devices']}
            self.assertFalse(routes['hidraw1']['virtual'])
            self.assertTrue(routes['hidraw13']['virtual'])
            self.assertEqual(routes['hidraw1']['steam_holders'], [{'pid': 123, 'fd': '0'}])
            self.assertEqual(routes['hidraw13']['steam_holders'], [{'pid': 123, 'fd': '1'}])
            self.assertIn({'pid':456,'fd':'0','name':'unrelated'},routes['hidraw1']['holders'])
            self.assertEqual(routes['hidraw1']['identity']['HID_ID'], '0003:0000054C:00000CE6')


    def test_bluetooth_uhid_sources_remain_physical_for_isolation(self):
        spec = importlib.util.spec_from_file_location('bluetooth_routes', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sysfs, proc, dev = (root/name for name in ('sys', 'proc', 'dev'))
            proc.mkdir()
            dev.mkdir()
            for name, identity in (('hidraw1', '0005:0000054C:00000CE6'),
                                   ('hidraw2', '0003:0000054C:00000CE6')):
                device = sysfs/'devices/virtual/misc/uhid'/name
                device.mkdir(parents=True)
                (device/'uevent').write_text('HID_ID=' + identity + '\n')
                link = sysfs/'class/hidraw'/name/'device'
                link.parent.mkdir(parents=True)
                link.symlink_to(device)
                (dev/name).touch()
            event = sysfs/'devices/virtual/misc/uhid/hidraw1/input/input1'
            event.mkdir(parents=True)
            (event/'uevent').write_text('PRODUCT=5/54c/ce6/100\n')
            link = sysfs/'class/input/event1/device'
            link.parent.mkdir(parents=True)
            link.symlink_to(event)
            (dev/'input').mkdir()
            (dev/'input/event1').touch()
            report = module.device_routes(sysfs, proc, dev)
            self.assertEqual(report['errors'], [])
            devices = {Path(device['node']).name: device for device in report['devices']}
            self.assertFalse(devices['hidraw1']['virtual'])
            self.assertTrue(devices['hidraw1']['sysfs_virtual'])
            self.assertTrue(devices['hidraw2']['virtual'])
            self.assertFalse(devices['event1']['virtual'])
            self.assertEqual(devices['event1']['identity']['HID_ID'], '0005:0000054C:00000CE6')


if __name__ == '__main__':
    unittest.main()
