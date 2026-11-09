#!/usr/bin/env python3
"""Physical controller support registry; detection never changes input routing."""
from pathlib import Path

# Match transport as well as model; emulated USB outputs are never sources.
PLAYSTATION_OUTPUT_ID = '0003:0000054C:00000CE6'
SUPPORTED_CONTROLLERS = {
    '0003:0000054C:00000CE6': {'name': 'USB DualSense', 'output': 'ds5-single', 'transport': 'usb'},
    '0005:0000054C:00000CE6': {'name': 'Bluetooth DualSense', 'output': 'ds5-single', 'transport': 'bluetooth'},
}

# Official standard Xbox One / One S / Series models. Transport is significant.
XBOX_USB_PRODUCTS = ('02D1', '02DD', '02EA', '0B12')
XBOX_BT_PRODUCTS = ('02E0', '02FD', '0B13', '0B20')
for bus, products, transport in (('0003', XBOX_USB_PRODUCTS, 'usb'),
                                  ('0005', XBOX_BT_PRODUCTS, 'bluetooth')):
    for product in products:
        SUPPORTED_CONTROLLERS[f'{bus}:0000045E:0000{product}'] = {
            'name': 'Xbox One / Series', 'output': 'xbox-series', 'transport': transport}


def normalized_identity(identity):
    if identity.get('HID_ID'):
        return identity['HID_ID'].upper()
    try:
        bus, vendor, product, _ = identity.get('PRODUCT', '').split('/')
        return f'{int(bus, 16):04X}:{int(vendor, 16):08X}:{int(product, 16):08X}'
    except ValueError:
        return ''


def source_identity(identity, sysfs_virtual=False):
    profile = SUPPORTED_CONTROLLERS.get(normalized_identity(identity))
    # BlueZ can expose physical Bluetooth HID through UHID. HSTN outputs use
    # USB HID identity, so the bus distinguishes these from Bluetooth sources.
    return bool(profile and (not sysfs_virtual or profile['transport'] == 'bluetooth'))


def supported_parent(source, sysfs=Path('/sys')):
    name = Path(source).name
    subsystem = 'hidraw' if name.startswith('hidraw') else 'input'
    device = (Path(sysfs)/'class'/subsystem/name/'device').resolve()
    virtual = Path(sysfs)/'devices/virtual' in device.parents
    candidate = None
    for parent in (device, *device.parents):
        try:
            identity = dict(line.split('=', 1) for line in (parent/'uevent').read_text().splitlines() if '=' in line)
            if source_identity(identity, virtual):
                if identity.get('HID_ID'):
                    return str(parent)
                # xpad exposes PRODUCT on the input root without a HID ancestor.
                candidate = str(parent)
        except OSError:
            pass
        if parent == Path(sysfs):
            break
    return candidate


def profile_for(source):
    parent = supported_parent(source)
    if parent:
        try:
            identity = dict(line.split('=', 1) for line in (Path(parent)/'uevent').read_text().splitlines() if '=' in line)
            return SUPPORTED_CONTROLLERS.get(normalized_identity(identity))
        except OSError:
            pass
    return None


def xbox_source(source):
    return (profile_for(source) or {}).get('output') == 'xbox-series'


def xbox_output(device):
    return device.get('virtual', False) and normalized_identity(device.get('identity', {})) == '0003:0000045E:00000B12'


def supported_sources(sources):
    """Never claim a composite containing an unrelated or unknown source."""
    return bool(sources) and all(supported_parent(source) for source in sources)


def physical_controllers(sysfs=Path('/sys')):
    """One display identity per physical controller, without collecting serials."""
    found = {}
    for pattern in ('class/hidraw/hidraw*', 'class/input/event*'):
        for node in Path(sysfs).glob(pattern):
            parent = supported_parent(node.name, sysfs)
            if not parent or parent in found:
                continue
            try:
                identity = dict(line.split('=', 1) for line in (Path(parent)/'uevent').read_text().splitlines() if '=' in line)
                profile = SUPPORTED_CONTROLLERS.get(normalized_identity(identity))
                if profile:
                    found[parent] = {'name': 'Xbox controller' if profile['output'] == 'xbox-series' else 'DualSense controller',
                                     'transport': profile['transport']}
            except OSError:
                pass
    return found


def connected(sysfs=Path('/sys')):
    return any(supported_parent(node.name, sysfs) for node in
               [*Path(sysfs).glob('class/hidraw/hidraw*'), *Path(sysfs).glob('class/input/event*')])


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
                == PLAYSTATION_OUTPUT_ID) or xbox_output(device)]
    composites = [composite for composite in report['inputplumber']['composites']
                  if supported_sources(composite.get('SourceDevicePaths', []))]
    return {**report, 'routes': {**report['routes'], 'devices': devices},
            'inputplumber': {**report['inputplumber'], 'composites': composites}}


if __name__ == '__main__':
    if connected():
        raise SystemExit(0)
    print('No supported controller connected; launcher startup continues while HSTN watches for hotplug.')
    raise SystemExit(1)
