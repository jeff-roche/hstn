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


LEGION_GO_S_MODELS = ('83L3', '83N6', '83Q2', '83Q3')
for product in ('E310', 'E311'):
    SUPPORTED_CONTROLLERS[f'0003:00001A86:0000{product}'] = {
        'name': 'Lenovo Legion Go S', 'output': 'preserve', 'transport': 'usb',
        'profile': 'legion-go-s'}


def legion_go_s_host(sysfs=Path('/sys')):
    try:
        dmi = Path(sysfs)/'class/dmi/id'
        return ((dmi/'sys_vendor').read_text().strip() == 'LENOVO' and
                (dmi/'product_name').read_text().strip() in LEGION_GO_S_MODELS)
    except OSError:
        return False


def normalized_identity(identity):
    if identity.get('HID_ID'):
        return identity['HID_ID'].upper()
    try:
        bus, vendor, product, _ = identity.get('PRODUCT', '').split('/')
        return f'{int(bus, 16):04X}:{int(vendor, 16):08X}:{int(product, 16):08X}'
    except ValueError:
        return ''


def source_identity(identity, sysfs_virtual=False, sysfs=Path('/sys')):
    profile = SUPPORTED_CONTROLLERS.get(normalized_identity(identity))
    # BlueZ can expose physical Bluetooth HID through UHID. HSTN outputs use
    # USB HID identity, so the bus distinguishes these from Bluetooth sources.
    return bool(profile and (not sysfs_virtual or profile['transport'] == 'bluetooth')
                and (profile.get('profile') != 'legion-go-s' or legion_go_s_host(sysfs)))


def supported_parent(source, sysfs=Path('/sys')):
    name = Path(source).name
    subsystem = ('leds' if name == 'go_s:rgb:joystick_rings' else
                 'hidraw' if name.startswith('hidraw') else 'input')
    device = (Path(sysfs)/'class'/subsystem/name/'device').resolve()
    if subsystem == 'leds':
        return str(device) if legion_go_s_host(sysfs) and (Path(sysfs)/'class/leds'/name).exists() else None
    virtual = Path(sysfs)/'devices/virtual' in device.parents
    candidate = None
    for parent in (device, *device.parents):
        try:
            identity = dict(line.split('=', 1) for line in (parent/'uevent').read_text().splitlines() if '=' in line)
            if source_identity(identity, virtual, sysfs):
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
        if Path(source).name == 'go_s:rgb:joystick_rings':
            return next(p for p in SUPPORTED_CONTROLLERS.values() if p.get('profile') == 'legion-go-s')
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
    sources = composite_sources(sources)
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
                    key = 'legion-go-s' if profile.get('profile') == 'legion-go-s' else parent
                    found[key] = {'name': profile['name'] if profile.get('profile') else ('Xbox controller' if profile['output'] == 'xbox-series' else 'DualSense controller'),
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
                == PLAYSTATION_OUTPUT_ID) or xbox_output(device) or handheld_output(device)]
    composites = [composite for composite in report['inputplumber']['composites']
                  if supported_sources(composite.get('SourceDevicePaths', []))]
    return {**report, 'routes': {**report['routes'], 'devices': devices},
            'inputplumber': {**report['inputplumber'], 'composites': composites}}




def composite_sources(sources):
    """Resolve Go S's device-less LED entry without discarding unknown inputs.

    InputPlumber versions that report devnode() for LED sources return an empty
    string. Accept exactly one such entry only alongside verified Go S inputs
    and the expected LED on a matching host.
    """
    sources = list(sources)
    if '' not in sources:
        return sources
    inputs = [source for source in sources if source]
    led = Path('/sys/class/leds/go_s:rgb:joystick_rings')
    if (sources.count('') != 1 or not inputs or not legion_go_s_host()
            or not led.exists()):
        return []
    if any((profile_for(source) or {}).get('profile') != 'legion-go-s' for source in inputs):
        return []
    if not any(Path(source).name.startswith(('hidraw', 'event')) for source in inputs):
        return []
    return [str(led) if source == '' else source for source in sources]


def composite_profile(sources):
    profiles = [profile_for(source) for source in composite_sources(sources)]
    if not profiles or any(profile is None for profile in profiles):
        return None
    names = {p.get('profile', 'xbox' if p['output'] == 'xbox-series' else 'playstation') for p in profiles}
    return names.pop() if len(names) == 1 else None


def preserved_composite(sources):
    return (composite_profile(sources) == 'legion-go-s' and
            any(Path(source).name != 'go_s:rgb:joystick_rings' for source in composite_sources(sources)))


def handheld_output(device):
    # Preserve InputPlumber's Xbox Elite or native Deck UHID output. The Deck
    # target can use Lenovo's Go S model ID. Steam's secondary 28de:11ff pad
    # is not the InputPlumber route and must not satisfy this check on its own.
    return device.get('virtual', False) and normalized_identity(device.get('identity', {})) in {
        '0003:0000045E:00000B00',
        '0003:000028DE:00001205',
        '0003:000028DE:000012FF',
    }


if __name__ == '__main__':
    if connected():
        raise SystemExit(0)
    print('No supported controller connected; launcher startup continues while HSTN watches for hotplug.')
    raise SystemExit(1)
