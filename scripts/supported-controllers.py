#!/usr/bin/env python3
"""Physical controller support registry; detection never changes input routing."""
from pathlib import Path

# Match transport as well as model; emulated USB outputs are never sources.
PLAYSTATION_OUTPUT_ID = '0003:0000054C:00000CE6'
SUPPORTED_CONTROLLERS = {
    '0003:0000054C:00000CE6': {'name': 'USB DualSense', 'output': 'ds5-single', 'transport': 'usb'},
    '0005:0000054C:00000CE6': {'name': 'Bluetooth DualSense', 'output': 'ds5-single', 'transport': 'bluetooth'},
}


def source_identity(identity, sysfs_virtual=False):
    profile = SUPPORTED_CONTROLLERS.get(identity.get('HID_ID', '').upper())
    # BlueZ can expose physical Bluetooth HID through UHID. HSTN outputs use
    # USB HID identity, so the bus distinguishes these from Bluetooth sources.
    return bool(profile and (not sysfs_virtual or profile['transport'] == 'bluetooth'))


def supported_parent(source, sysfs=Path('/sys')):
    name = Path(source).name
    subsystem = 'hidraw' if name.startswith('hidraw') else 'input'
    device = (Path(sysfs)/'class'/subsystem/name/'device').resolve()
    virtual = Path(sysfs)/'devices/virtual' in device.parents
    for parent in (device, *device.parents):
        try:
            identity = dict(line.split('=', 1) for line in (parent/'uevent').read_text().splitlines() if '=' in line)
            if source_identity(identity, virtual):
                return str(parent)
        except OSError:
            pass
        if parent == Path(sysfs):
            break
    return None


def supported_sources(sources):
    """Never claim a composite containing an unrelated or unknown source."""
    return bool(sources) and all(supported_parent(source) for source in sources)


def connected(sysfs=Path('/sys')):
    return any(supported_parent(node.name, sysfs) for node in
               (Path(sysfs)/'class/hidraw').glob('hidraw*'))


def activation_issues(sources=None):
    """Do not take over a physical controller Steam has already opened."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('activation_routes', Path(__file__).with_name('controller-route-snapshot.py'))
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    roots = {supported_parent(source) for source in sources} if sources else None
    report = routes.device_routes()
    issues = list(report['errors'])
    for device in report['devices']:
        if (not device['virtual'] and supported_parent(device['node']) and device['steam_holders']
                and (roots is None or supported_parent(device['node']) in roots)):
            issues.append('Steam already holds a supported physical controller; reconnect it with Steam closed to enable HSTN interception')
    return issues


def isolation_report(report):
    """Scope readiness to supported physical groups and their virtual outputs."""
    devices = [device for device in report['routes']['devices']
               if supported_parent(device['node']) or
               (device['virtual'] and device.get('identity', {}).get('HID_ID', '').upper()
                == PLAYSTATION_OUTPUT_ID)]
    composites = [composite for composite in report['inputplumber']['composites']
                  if supported_sources(composite.get('SourceDevicePaths', []))]
    return {**report, 'routes': {**report['routes'], 'devices': devices},
            'inputplumber': {**report['inputplumber'], 'composites': composites}}


if __name__ == '__main__':
    if connected():
        raise SystemExit(0)
    print('No supported controller connected; launcher startup continues while HSTN watches for hotplug.')
    raise SystemExit(1)
