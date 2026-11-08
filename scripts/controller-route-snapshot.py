#!/usr/bin/env python3
"""Read-only controller route evidence. Never reads reports or changes routing.

Run while the failing Gamescope session/overlay is active, redirecting stdout
to a JSON file. Desktop evidence cannot establish a previous session's routes.
No process environments, command arguments, or controller serials are collected.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess


def device_routes(sysfs=Path('/sys'), proc=Path('/proc'), dev=Path('/dev')):
    errors, devices, holder_errors = [], [], []
    entries = [*sysfs.glob('class/hidraw/hidraw*'), *sysfs.glob('class/input/event*')]
    for entry in sorted(entries):
        node = dev / ('input' if entry.name.startswith('event') else '') / entry.name
        try:
            device = (entry / 'device').resolve(strict=True)
            relative = device.relative_to(sysfs / 'devices')
            identity = {}
            event_file = device / 'uevent'
            if event_file.exists():
                for line in event_file.read_text().splitlines():
                    key, _, value = line.partition('=')
                    if key in ('HID_ID', 'HID_NAME', 'PRODUCT', 'NAME'):
                        identity[key] = value
            devices.append({'node': str(node), 'sysfs': str(device),
                            'virtual': relative.parts[0] == 'virtual',
                            'mode': oct(node.stat().st_mode & 0o777),
                            'readable_now': os.access(node, os.R_OK),
                            'identity': identity, 'steam_holders': [], 'holders': []})
        except (OSError, ValueError) as error:
            errors.append(f'{entry.name}: {error}')
    by_node = {route['node']: route for route in devices}
    for process in sorted(proc.iterdir()):
        if not process.name.isdigit():
            continue
        name = ''
        try:
            if process.stat().st_uid != os.getuid():
                continue
            name = (process / 'comm').read_text().strip()
            for fd in (process / 'fd').iterdir():
                try:
                    target = os.readlink(fd)
                except FileNotFoundError:  # Descriptor closed during snapshot.
                    continue
                if target in by_node:
                    by_node[target]['holders'].append({'pid': int(process.name), 'fd': fd.name, 'name': name})
                    if name in ('steam', 'steam.exe'):
                        by_node[target]['steam_holders'].append({'pid': int(process.name), 'fd': fd.name})
        except FileNotFoundError:  # Process exited during snapshot.
            continue
        except OSError as error:
            target_errors = errors if name in ('steam', 'steam.exe') else holder_errors
            target_errors.append(f'Process {process.name}: {error}')
    return {'devices': devices, 'errors': errors, 'holder_inspection_errors': holder_errors}


def inputplumber_state():
    service = 'org.shadowblip.InputPlumber'
    manager = '/org/shadowblip/InputPlumber/Manager'
    report = {'composites': [], 'errors': []}

    def property_value(path, interface, name):
        result = subprocess.run(['busctl', '--system', '--json=short', 'get-property',
                                 service, path, interface, name],
                                capture_output=True, text=True, timeout=3, check=True)
        return json.loads(result.stdout)['data']

    try:
        report['manage_all_devices'] = property_value(manager, 'org.shadowblip.InputManager', 'ManageAllDevices')
        tree = subprocess.run(['busctl', '--system', '--list', 'tree', service],
                              capture_output=True, text=True, timeout=3, check=True)
        for path in tree.stdout.splitlines():
            if not path.rsplit('/', 1)[-1].startswith('CompositeDevice'):
                continue
            composite = {'path': path}
            report['composites'].append(composite)
            for name in ('InterceptMode', 'SourceDevicePaths', 'TargetDevices', 'DbusDevices'):
                try:
                    composite[name] = property_value(path, 'org.shadowblip.Input.CompositeDevice', name)
                except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
                    report['errors'].append(f'{path} {name}: {error}')
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as error:
        report['errors'].append(str(error))
    return report


def isolation_issues(report, single_playstation=False):
    """Necessary preflight conditions, not proof of live event isolation."""
    routes = report['routes']
    state = report['inputplumber']
    issues = [*routes['errors'], *state['errors']]
    composites = state['composites']
    if not composites:
        issues.append('No managed controllers discovered')
    devices = {device['node']: device for device in routes['devices']}
    suppressed = set()
    if single_playstation:
        sony_id = '0003:0000054C:00000CE6'
        primary_roots = []
        for composite in composites:
            if not composite.get('TargetDevices'):
                continue
            for source in composite.get('SourceDevicePaths', []):
                device = devices.get(source, {})
                if (source.startswith('/dev/hidraw') and not device.get('virtual', True)
                        and device.get('identity', {}).get('HID_ID') == sony_id):
                    primary_roots.append(device.get('sysfs', ''))
        if primary_roots:
            virtual_pads = [d for d in devices.values() if d['virtual'] and
                '/hidraw' in d['node'] and d.get('identity', {}).get('HID_ID') == sony_id]
            if len(primary_roots) != 1 or len(virtual_pads) != 1:
                issues.append('Expected one physical-source and one virtual PlayStation output')
            for composite in composites:
                sources = composite.get('SourceDevicePaths', [])
                if not sources or composite.get('TargetDevices'):
                    continue
                if all(source.startswith('/dev/input/event') and source in devices and
                       not devices[source]['virtual'] and
                       any(root and devices[source].get('sysfs', '').startswith(root + '/input/')
                           for root in primary_roots) for source in sources):
                    suppressed.add(composite.get('path'))
    for composite in composites:
        if composite.get('InterceptMode') not in (1, 2):
            issues.append('Controller interception is not active')
        if not composite.get('DbusDevices') or (not composite.get('TargetDevices') and composite.get('path') not in suppressed):
            issues.append('Controller targets are not ready')
        sources = composite.get('SourceDevicePaths', [])
        if not sources:
            issues.append('Controller sources are not known')
        for source in sources:
            device = devices.get(source)
            if device is None:
                issues.append(f'Cannot inspect controller source: {source}')
            elif not device['virtual'] and device['readable_now']:
                issues.append(f'Physical source remains readable: {source}')
    for device in devices.values():
        if not device['virtual'] and device['steam_holders']:
            issues.append(f'Steam already holds physical source: {device["node"]}')
    if not any(device['virtual'] and device['readable_now'] for device in devices.values()):
        issues.append('No readable virtual input route found')
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-isolation', action='store_true', help='Check necessary preflight conditions; returns 1 when blocked')
    parser.add_argument('--single-playstation', action='store_true', help='Require one virtual DualSense; allow safely suppressed physical siblings')
    args = parser.parse_args()
    report = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'routes': device_routes(), 'inputplumber': inputplumber_state()}
    if args.check_isolation:
        report["isolation_issues"] = isolation_issues(report, single_playstation=args.single_playstation)
    print(json.dumps(report, indent=2))
    return int(bool(report.get("isolation_issues")))


if __name__ == '__main__':
    raise SystemExit(main())
