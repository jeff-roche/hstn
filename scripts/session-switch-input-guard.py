#!/usr/bin/env python3
"""Maintain the narrow InputPlumber HID rule correction across sessions.

Installed as root-owned code under /usr/local/libexec. Reserves supported physical
sources before udev grants session access, including hotplug between sessions.
Never enables controller management or changes launcher settings.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import tempfile
import time

RULE_NAME=re.compile(r'(50|96)-inputplumber-hide-(hidraw[0-9]+)-(early|late)\.rules')
RUNTIME=Path('/run/session-switch-input-guard')
RULES=Path('/run/udev/rules.d')
SOURCE_RULE_NAME='72-hstn-controller-sources.rules'
# Run after 70-uaccess/71-seat, but before 73-seat-late grants the active user's
# ACL. Final permission assignments also prevent later vendor rules reopening
# the sources. Match HID ancestry, never reusable hidraw/event numbers. BlueZ
# UHID sources use bus 0005; InputPlumber's virtual USB outputs use bus 0003.
SOURCE_RULE='''# HSTN: reserve supported physical controller sources for root InputPlumber.
ACTION!="add|change", GOTO="hstn_sources_end"
SUBSYSTEM!="hidraw|input", GOTO="hstn_sources_end"
KERNEL!="hidraw*|event*|js*|mouse*", GOTO="hstn_sources_end"
DEVPATH=="/devices/virtual/*", KERNELS=="0003:054C:0CE6.*", GOTO="hstn_sources_end"
SUBSYSTEMS=="hid", KERNELS=="0003:054C:0CE6.*|0005:054C:0CE6.*", TAG-="uaccess", OWNER:="root", GROUP:="root", MODE:="0600"
DEVPATH=="/devices/virtual/*", ATTRS{id/bustype}=="0003", GOTO="hstn_sources_end"
SUBSYSTEMS=="input", ATTRS{id/bustype}=="0003", ATTRS{id/vendor}=="045e", ATTRS{id/product}=="02d1|02dd|02ea|0b12", TAG-="uaccess", OWNER:="root", GROUP:="root", MODE:="0600"
SUBSYSTEMS=="hid", KERNELS=="0005:045E:02E0.*|0005:045E:02FD.*|0005:045E:0B13.*|0005:045E:0B20.*", TAG-="uaccess", OWNER:="root", GROUP:="root", MODE:="0600"
SUBSYSTEMS=="input", ATTRS{id/bustype}=="0005", ATTRS{id/vendor}=="045e", ATTRS{id/product}=="02e0|02fd|0b13|0b20", TAG-="uaccess", OWNER:="root", GROUP:="root", MODE:="0600"
ATTR{[dmi/id]sys_vendor}!="LENOVO", GOTO="hstn_sources_end"
ATTR{[dmi/id]product_name}!="83L3|83N6|83Q2|83Q3", GOTO="hstn_sources_end"
DEVPATH=="/devices/virtual/*", GOTO="hstn_sources_end"
SUBSYSTEMS=="hid", KERNELS=="0003:1A86:E310.*|0003:1A86:E311.*", TAG-="uaccess", OWNER:="root", GROUP:="root", MODE:="0600"
SUBSYSTEMS=="input", ATTRS{id/bustype}=="0003", ATTRS{id/vendor}=="1a86", ATTRS{id/product}=="e310|e311", TAG-="uaccess", OWNER:="root", GROUP:="root", MODE:="0600"
LABEL="hstn_sources_end"
'''


# Standalone root-owned copy of source detection; parity is tested.
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


def supported_source_paths(sysfs=Path('/sys')):
    return [str(entry) for pattern in ('class/hidraw/hidraw*', 'class/input/event*',
                                      'class/input/js*', 'class/input/mouse*')
            for entry in Path(sysfs).glob(pattern) if supported_parent(entry.name, sysfs)]


def refresh_sources():
    refresh_paths(supported_source_paths())


def correct_rule(text,node):
    lines=text.splitlines(keepends=True)
    for index,line in enumerate(lines):
        if (line.startswith('ACTION=="add|change", SUBSYSTEMS=="hidraw", ')
                and f'KERNEL=="{node}",' in line and 'KERNELS==' in line):
            lines[index]=line.replace('SUBSYSTEMS=="hidraw"','SUBSYSTEM=="hidraw"',1)
    return ''.join(lines)


def physical_node(node, sysfs=Path('/sys')):
    device = Path(sysfs)/'class/hidraw'/node/'device'
    if not device.exists():
        return False
    if Path(sysfs)/'devices/virtual' not in device.resolve().parents:
        return True
    # BlueZ physical Bluetooth sources can live under virtual/misc/uhid.
    # Keep USB-emulated HSTN outputs excluded. This root helper stays standalone.
    try:
        return bool(supported_parent(node, sysfs))
    except OSError:
        return False


def refresh_nodes(nodes):
    paths=[str(Path('/sys/class/hidraw')/node) for node in sorted(nodes)
           if (Path('/sys/class/hidraw')/node).exists()]
    refresh_paths(paths)


def refresh_paths(paths):
    subprocess.run(['udevadm','control','--reload-rules'],check=True,timeout=10)
    if paths:
        subprocess.run(['udevadm','trigger','--action=change',*paths],check=True,timeout=15)
    subprocess.run(['udevadm','settle','--timeout=15'],check=True,timeout=20)


def atomic_json(path,data,mode=0o600):
    fd,name=tempfile.mkstemp(prefix='.pending-',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


class SourceReservation:
    """Journal the runtime rule; retain recovery data until udev acknowledges it."""
    def __init__(self, guard, refresh=refresh_sources):
        self.guard=guard
        self.path=guard.rules/SOURCE_RULE_NAME
        self.journal=guard.state/'source-reservation.json'
        self.refresh=refresh
        self.record=None
        if self.journal.exists() or self.journal.is_symlink():
            with guard.open_trusted(self.journal,private=True) as stream:
                self.record=json.load(stream)
            if (not isinstance(self.record,dict) or self.record.get('version')!=1 or
                    not isinstance(self.record.get('fingerprint'),(list,type(None)))):
                raise ValueError('Invalid source reservation journal')

    def owned(self):
        with self.guard.open_trusted(self.path) as stream:
            info=os.fstat(stream.fileno())
            fingerprint=[info.st_dev,info.st_ino]
            if (not self.record or stream.read(len(SOURCE_RULE)+1)!=SOURCE_RULE or
                    self.record['fingerprint'] not in (None,fingerprint)):
                raise ValueError(f'Preserving changed source reservation: {self.path}')
            return fingerprint

    def install(self):
        if self.path.exists() or self.path.is_symlink():
            fingerprint=self.owned()
        else:
            # Record intent before linking a complete file into udev's rules.
            self.record={'version':1,'fingerprint':None}
            atomic_json(self.journal,self.record)
            fd,name=tempfile.mkstemp(prefix='.hstn-sources-',dir=self.guard.rules)
            try:
                with os.fdopen(fd,'w') as stream:
                    os.fchmod(stream.fileno(),0o644)
                    stream.write(SOURCE_RULE);stream.flush();os.fsync(stream.fileno())
                os.link(name,self.path)  # Refuse a concurrent writer, never overwrite.
            finally:Path(name).unlink(missing_ok=True)
            fingerprint=self.owned()
        self.record={'version':1,'fingerprint':fingerprint}
        atomic_json(self.journal,self.record)
        # Also refresh on recovery: a previous reload/trigger may have failed.
        self.refresh()

    def restore(self):
        if not self.record:return
        if self.path.exists() or self.path.is_symlink():
            self.owned()
            self.path.unlink()
        self.refresh()
        self.journal.unlink()
        self.record=None


class RuleGuard:
    def __init__(self,rules=RULES,state=RUNTIME,*,physical=physical_node,
                 refresh=refresh_nodes,owner_uid=0):
        self.rules=Path(rules);self.state=Path(state);self.physical=physical
        self.refresh=refresh;self.owner_uid=owner_uid
        for directory in (self.rules,self.state):
            directory.mkdir(mode=0o755,parents=True,exist_ok=True)
            info=directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=owner_uid or info.st_mode & 0o022:
                raise ValueError(f'Unsafe guard directory: {directory}')
        self.journal=self.state/'backups.json';self.saved={}
        if self.journal.exists():
            with self.open_trusted(self.journal,private=True) as stream:
                self.saved=json.load(stream)
            for name,entry in self.saved.items():
                match=RULE_NAME.fullmatch(name)
                if (not match or entry['node']!=match[2] or
                    correct_rule(entry['original'],match[2])!=entry['corrected']):
                    raise ValueError('Invalid input guard backup journal')
        self.recovery_refresh=bool(self.saved)

    def open_trusted(self,path,private=False):
        fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=self.owner_uid or
                info.st_mode & (0o077 if private else 0o022)):
                raise ValueError(f'Unsafe generated input rule or journal: {path}')
            return os.fdopen(fd,'r+')
        except BaseException:
            os.close(fd);raise

    def save(self):atomic_json(self.journal,self.saved)

    def scan_once(self):
        changed=set();present=set()
        for path in sorted(self.rules.glob('*-inputplumber-hide-hidraw*-*.rules')):
            match=RULE_NAME.fullmatch(path.name)
            if not match:continue
            present.add(path.name);node=match[2]
            if not self.physical(node):continue
            try:
                with self.open_trusted(path) as stream:
                    info=os.fstat(stream.fileno());fingerprint=[info.st_dev,info.st_ino]
                    text=stream.read(65537)
                    if len(text)>65536:raise ValueError(f'Oversized generated input rule: {path}')
                    prior=self.saved.get(path.name)
                    if prior and (prior['fingerprint']!=fingerprint or text!=prior['corrected']):
                        del self.saved[path.name];self.save()
                    corrected=correct_rule(text,node)
                    if corrected==text:continue
                    self.saved[path.name]={'original':text,'corrected':corrected,
                                           'node':node,'fingerprint':fingerprint}
                    self.save()  # Journal first: retain rollback across crashes/restarts.
                    stream.seek(0)
                    current=path.stat()
                    if ([current.st_dev,current.st_ino]!=fingerprint or stream.read()!=text):
                        del self.saved[path.name];self.save();continue
                    stream.seek(0);stream.write(corrected);stream.truncate();stream.flush();os.fsync(stream.fileno())
                    changed.add(node)
                    print(f'Corrected {path.name}',flush=True)
            except FileNotFoundError:continue  # InputPlumber removed it during teardown.
        expired=set(self.saved)-present
        if expired:
            for name in expired:del self.saved[name]
            self.save()
        recovered={entry['node'] for entry in self.saved.values()
                   if self.recovery_refresh and self.physical(entry['node'])}
        if changed or recovered:self.refresh(changed|recovered)
        self.recovery_refresh=False
        if recovered:print('Reapplied retained input rule corrections after restart.',flush=True)
        return changed

    def restore(self):
        changed=set()
        for name,entry in list(self.saved.items()):
            try:
                with self.open_trusted(self.rules/name) as stream:
                    info=os.fstat(stream.fileno())
                    if [info.st_dev,info.st_ino]!=entry['fingerprint'] or stream.read()!=entry['corrected']:
                        continue
                    stream.seek(0);stream.write(entry['original']);stream.truncate();stream.flush();os.fsync(stream.fileno())
                    changed.add(entry['node'])
            except FileNotFoundError:pass
            except (OSError,ValueError) as error:print(f'Rule restore skipped: {error}',flush=True)
        self.saved.clear();self.save()
        if changed:self.refresh(changed)



# This socket accepts only a composite path, never caller-supplied mappings,
# file paths, commands, or YAML. The peer must own the active local seat.
DESKTOP_MAP_SOCKET = RUNTIME/'desktop-map.sock'
COMPOSITE_PATH = re.compile(r'/org/shadowblip/InputPlumber/CompositeDevice[0-9]+')
NAV_BUTTONS = {'DPadUp': 'ui_up', 'DPadDown': 'ui_down',
               'DPadLeft': 'ui_left', 'DPadRight': 'ui_right',
               'South': 'ui_accept', 'East': 'ui_back',
               'LeftBumper': 'ui_l1', 'RightBumper': 'ui_r1'}


def desktop_navigation_profile(original):
    """Preserve unrelated mappings and outputs; consume only HSTN controls."""
    import copy
    import yaml
    if len(original) > 65536:
        raise ValueError('Controller profile is too large for Desktop HSTN')
    result = yaml.safe_load(original)
    if (not isinstance(result, dict) or result.get('version') != 1
            or result.get('kind') != 'DeviceProfile'
            or not isinstance(result.get('mapping'), list)
            or result.get('target_devices') is not None):
        raise ValueError('Desktop split input needs a version 1 profile without target overrides')
    result = copy.deepcopy(result)
    result.pop('target_devices', None)
    result['name'] = 'HSTN Desktop Navigation'
    mappings = []
    for mapping in result['mapping']:
        source = mapping.get('source_event', {}).get('gamepad', {})
        if source.get('button') in NAV_BUTTONS or source.get('axis', {}).get('name') == 'LeftStick':
            continue
        mappings.append(mapping)
    for button, action in NAV_BUTTONS.items():
        mappings.append({'name': 'HSTN ' + button,
                         'source_event': {'gamepad': {'button': button}},
                         'target_events': [{'dbus': action}]})
    mappings.append({'name': 'HSTN LeftStick',
                     'source_event': {'gamepad': {'axis': {'name': 'LeftStick'}}},
                     'target_events': [{'dbus': 'ui_' + direction}
                                       for direction in ('up', 'down', 'left', 'right')]})
    result['mapping'] = mappings
    return result


def profile_bus(path, operation, *args):
    prefix = ['busctl', '--system', '--json=short']
    interface = 'org.shadowblip.Input.CompositeDevice'
    service = 'org.shadowblip.InputPlumber'
    if operation == 'exists':
        result = subprocess.run(['busctl', '--system', '--list', 'tree', service],
                                capture_output=True, text=True, check=True, timeout=5)
        return path in result.stdout.splitlines()
    command = (prefix + ['get-property', service, path, interface, operation[4:]]
               if operation.startswith('get:') else
               prefix + ['call', service, path, interface, operation, *args])
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=5)
    if not result.stdout.strip():
        return None
    data = json.loads(result.stdout)['data']
    return data[0] if operation in ('GetProfileYaml',) else data


def active_seat_uid():
    def value(*args):
        return subprocess.run(['loginctl', *args], capture_output=True, text=True,
                              check=True, timeout=3).stdout.strip()
    session = value('show-seat', 'seat0', '-p', 'ActiveSession', '--value')
    if not session:
        raise ValueError('No active local seat')
    return int(value('show-session', session, '-p', 'User', '--value'))


def desktop_map_sources(sources):
    if not legion_go_s_host() or not sources or sources.count('') > 1:
        return False
    if '' in sources and not Path('/sys/class/leds/go_s:rgb:joystick_rings').exists():
        return False
    inputs = [source for source in sources if source and Path(source).name != 'go_s:rgb:joystick_rings']
    if not inputs:
        return False
    for source in inputs:
        parent = supported_parent(source)
        if not parent:
            return False
        try:
            identity = dict(line.split('=', 1) for line in (Path(parent)/'uevent').read_text().splitlines() if '=' in line)
            if SUPPORTED_CONTROLLERS.get(normalized_identity(identity), {}).get('profile') != 'legion-go-s':
                return False
        except OSError:
            return False
    return all(not source or supported_parent(source) for source in sources)


class DesktopProfileBridge:
    """Root-owned, fixed-purpose profile lease with journal-before-write recovery."""
    def __init__(self, guard, *, bus=profile_bus, active_uid=active_seat_uid):
        self.guard, self.bus, self.active_uid = guard, bus, active_uid
        self.journal = guard.state/'desktop-profiles.json'
        self.records = {}
        self.client = None
        self.client_path = None
        self.buffer = b''
        self.server = None
        if self.journal.exists():
            with guard.open_trusted(self.journal, private=True) as stream:
                self.records = json.load(stream)
            for path, record in self.records.items():
                if (not COMPOSITE_PATH.fullmatch(path) or not isinstance(record.get('original'), str)
                        or not isinstance(record.get('applied'), dict)):
                    raise ValueError('Invalid Desktop profile recovery record')
        self.restore_all()

    def save(self):
        if self.records:
            atomic_json(self.journal, self.records)
        else:
            self.journal.unlink(missing_ok=True)

    def apply(self, path):
        import yaml
        if (not COMPOSITE_PATH.fullmatch(path)
                or not desktop_map_sources(self.bus(path, 'get:SourceDevicePaths'))):
            raise ValueError('Desktop mapping requires a verified Go S composite')
        if self.records:
            raise ValueError('A Desktop mapping is already leased or needs recovery')
        if self.bus(path, 'get:ProfilePath'):
            raise ValueError('A file-backed profile must be preserved; Desktop split mapping was refused')
        original = self.bus(path, 'GetProfileYaml')
        applied = desktop_navigation_profile(original)
        self.records[path] = {'original': original, 'applied': applied,
                              'sources': sorted(self.bus(path, 'get:SourceDevicePaths'))}
        self.save()
        try:
            self.bus(path, 'LoadProfileFromYaml', 's', json.dumps(applied))
            if yaml.safe_load(self.bus(path, 'GetProfileYaml')) != applied:
                raise ValueError('InputPlumber did not install the expected Desktop mapping')
        except Exception:
            self.restore_all()
            raise

    def check(self, path):
        """Keep our leased navigation when a manager re-sends its exact baseline.

        DeckyPlumber re-applies Default when Steam's active app changes. Only the
        recorded baseline may be overlaid again; distinct edits are preserved.
        """
        import yaml
        record = self.records[path]
        sources = self.bus(path, 'get:SourceDevicePaths')
        if (sorted(sources) != record.get('sources') or not desktop_map_sources(sources)
                or self.bus(path, 'get:ProfilePath')):
            raise ValueError('Desktop controller ownership changed')
        current = yaml.safe_load(self.bus(path, 'GetProfileYaml'))
        if current == record['applied']:
            return False
        if current != yaml.safe_load(record['original']):
            raise ValueError('Desktop profile changed externally; preserving the new profile')
        self.bus(path, 'LoadProfileFromYaml', 's', json.dumps(record['applied']))
        if yaml.safe_load(self.bus(path, 'GetProfileYaml')) != record['applied']:
            raise ValueError('Desktop navigation could not be re-established')
        print('Desktop navigation restored after baseline profile reset', flush=True)
        return True

    def restore_all(self):
        if not self.records:
            return
        import yaml
        for path, record in list(self.records.items()):
            if not self.bus(path, 'exists'):
                # Destroying the composite also destroys its temporary profile.
                del self.records[path]
                self.save()
                continue
            if (record.get('sources') is not None
                    and sorted(self.bus(path, 'get:SourceDevicePaths')) != record['sources']):
                raise ValueError('Desktop controller sources changed; recovery record retained')
            if self.bus(path, 'get:ProfilePath'):
                raise ValueError('Desktop profile became file-backed; recovery record retained')
            current = yaml.safe_load(self.bus(path, 'GetProfileYaml'))
            if current == record['applied']:
                self.bus(path, 'LoadProfileFromYaml', 's', record['original'])
                current = yaml.safe_load(self.bus(path, 'GetProfileYaml'))
            if current != yaml.safe_load(record['original']):
                raise ValueError('Desktop profile changed externally; recovery record retained')
            del self.records[path]
            self.save()

    def start(self):
        self.path = self.guard.state/'desktop-map.sock'
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.guard.owner_uid:
                raise ValueError('Unsafe Desktop mapping socket')
            self.path.unlink()
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(self.path))
        self.path.chmod(0o666)
        self.server.listen(1)

    def disconnect(self):
        if self.client:
            self.client.close()
        self.client, self.client_path, self.buffer = None, None, b''
        try:
            self.restore_all()
        except Exception as error:
            # A changed profile retains its recovery journal. It must not stop
            # the independent physical-source reservation/udev guard.
            print('Desktop mapping recovery retained: ' + str(error), flush=True)

    def poll(self, timeout=.5):
        import select
        import struct
        sockets = ([self.client] if self.client else []) + [self.server]
        for ready in select.select(sockets, [], [], timeout)[0]:
            if ready is self.server:
                client, _ = self.server.accept()
                _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                try:
                    if self.client or uid != self.active_uid():
                        raise ValueError('Desktop mapping requires the active local user')
                    self.client = client
                    self.client_uid = uid
                    self.buffer = b''
                except Exception:
                    client.close()
                continue
            try:
                data = self.client.recv(4096)
                if not data:
                    self.disconnect()
                    continue
                self.buffer += data
                if len(self.buffer) > 4096:
                    raise ValueError('Desktop mapping request too large')
                if b'\n' not in self.buffer:
                    continue
                request, self.buffer = self.buffer.split(b'\n', 1)
                request = json.loads(request)
                if self.client_uid != self.active_uid():
                    raise ValueError('Desktop mapping seat ownership changed')
                response = {'ok': True}
                if set(request) == {'open'} and isinstance(request['open'], str) and self.client_path is None:
                    self.apply(request['open'])
                    self.client_path = request['open']
                elif request == {'close': True} and self.client_path:
                    self.restore_all()
                    self.client_path = None
                elif request == {'check': True} and self.client_path:
                    response['repaired'] = self.check(self.client_path)
                else:
                    raise ValueError('Unsupported Desktop mapping request')
                self.client.sendall(json.dumps(response).encode() + b'\n')
            except Exception as error:
                print('Desktop mapping: ' + str(error), flush=True)
                if self.client:
                    try:self.client.sendall(json.dumps({'error': str(error)}).encode() + b'\n')
                    except OSError:pass
                self.disconnect()

    def close(self):
        try:
            self.disconnect()
        finally:
            if self.server:
                self.server.close()
                self.path.unlink(missing_ok=True)

def notify(message):
    address=os.environ.get('NOTIFY_SOCKET')
    if not address:return
    if address.startswith('@'):address='\0'+address[1:]
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sock:
            sock.connect(address);sock.sendall(message.encode())
        return True
    except OSError as error:
        print(f'Systemd notification failed: {error}',flush=True);return False


def legacy_active():
    path=Path('/run/session-switch-input-diagnostic.active')
    try:
        pid=int(path.read_text().strip())
        if path.stat().st_uid!=0 or pid<=1:return False
        os.kill(pid,0);return True
    except (OSError,ValueError):return False


def main():
    if os.geteuid()!=0:raise SystemExit('This helper must run as the system session-switch-input-guard service.')
    os.umask(0o077)
    RUNTIME.mkdir(mode=0o755,parents=True,exist_ok=True)
    info=RUNTIME.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
        raise SystemExit('Unsafe input guard runtime directory')
    RUNTIME.chmod(0o755)
    lock_fd=os.open(RUNTIME/'lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if legacy_active():raise SystemExit('Stop session-switch-input-diagnostic.service before starting the permanent guard.')
    guard=RuleGuard();reservation=SourceReservation(guard);running=True;active=RUNTIME/'active'
    desktop_profiles = DesktopProfileBridge(guard)
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        reservation.install()
        guard.scan_once()
        desktop_profiles.start()
        ticks=int(Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19])
        atomic_json(active,{'version':1,'kind':'session-switch-input-guard','pid':os.getpid(),'start_ticks':ticks},0o644)
        if notify('READY=1\nSTATUS=Watching InputPlumber runtime HID rules') is False:
            raise RuntimeError('Could not notify systemd that input guard is ready')
        print('Input guard ready; watching across sessions.',flush=True)
        while running:
            reservation.owned()
            guard.scan_once();desktop_profiles.poll(.5)
    finally:
        notify('STOPPING=1')
        active.unlink(missing_ok=True)
        try:
            desktop_profiles.close()
            if not running:
                try:guard.restore()
                finally:reservation.restore()
                print('Input guard stopped; surviving owned rule changes restored.',flush=True)
            else:
                print('Input guard failed; corrected rules and journal retained for restart.',flush=True)
        finally:os.close(lock_fd)


if __name__=='__main__':main()
