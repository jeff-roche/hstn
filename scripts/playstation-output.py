#!/usr/bin/env python3
"""Single DualSense output for an overlay-owned, temporary controller group."""
import os
from pathlib import Path
import time


def parent_for(source):
    node = Path(source).name
    subsystem = 'hidraw' if node.startswith('hidraw') else 'input'
    device = (Path('/sys/class')/subsystem/node/'device').resolve()
    if '/devices/virtual/' in str(device):
        return None
    for parent in (device, *device.parents):
        try:
            if 'HID_ID=0003:0000054C:00000CE6' in (parent/'uevent').read_text():
                return str(parent)
        except OSError:
            pass
    return None


def required_for(source):
    parent = parent_for(source)
    if parent is None:
        return set()
    required = {source}
    for node in Path(parent).glob('input/input*/event*'):
        try:
            name = (node.parent/'name').read_text().strip()
        except OSError:
            continue
        if name.endswith(('Wireless Controller', 'Motion Sensors', 'Touchpad')):
            required.add('/dev/input/'+node.name)
    return required


def virtual_nodes():
    found = []
    for node in Path('/sys/class/hidraw').glob('hidraw*'):
        device = (node/'device').resolve()
        try:
            if '/devices/virtual/' in str(device) and 'HID_ID=0003:0000054C:00000CE6' in (device/'uevent').read_text():
                found.append(str(node))
        except OSError:
            pass
    return found


def virtual_devices(root=Path('/sys/devices/virtual/misc/uhid')):
    """Include failed/unbound UHID devices, which may never expose hidraw."""
    found = []
    for device in Path(root).glob('*'):
        try:
            if 'HID_ID=0003:0000054C:00000CE6' in (device/'uevent').read_text():
                found.append(str(device))
        except OSError:
            pass
    return sorted(found)


def pad_ready():
    nodes = virtual_nodes()
    if len(nodes) != 1:
        return False
    parent = (Path(nodes[0])/'device').resolve()
    try:
        if (parent/'driver').resolve().name != 'playstation':
            return False
    except OSError:
        return False
    for node in parent.glob('input/input*/event*'):
        try:
            name = (node.parent/'name').read_text().strip()
            if name.endswith('Wireless Controller') and os.access('/dev/input/'+node.name, os.R_OK):
                return True
        except OSError:
            pass
    return False


class PlayStationOutput:
    def __init__(self, set_targets, *, parent_for=parent_for, required_for=required_for,
                 virtual_devices=virtual_devices, pad_ready=pad_ready,
                 clock=time.monotonic, binding_timeout=10, max_binding_attempts=3,
                 drain_timeout=15):
        self.set_targets = set_targets
        self.parent_for = parent_for
        self.required_for = required_for
        self.virtual_devices = virtual_devices
        self.pad_ready = pad_ready
        self.clock = clock
        self.binding_timeout = binding_timeout
        self.max_binding_attempts = max_binding_attempts
        self.binding_attempts = 0
        self.binding_started = None
        self.drain_timeout = drain_timeout
        self.drain_started = None
        self.failure = None
        self.plan = None
        self.phase = 'discover'
        self.companions = set()

    def drain(self, group):
        self.phase = 'draining'
        self.drain_started = self.clock()
        try:
            for record in group:
                self.set_targets(record['path'], ['null'])
        except Exception as error:
            self.fail(f'PlayStation output drain failed: {error}')

    def fail(self, message):
        self.phase = 'failed'
        self.failure = message
        raise RuntimeError(message)

    def update(self, records):
        primaries = [(record, source) for record in records for source in record['sources']
                     if source.startswith('/dev/hidraw') and self.parent_for(source)]
        if not primaries:
            return self.plan is None
        if len(primaries) != 1:
            raise RuntimeError('Single-output PlayStation test requires exactly one physical USB DualSense')
        primary, source = primaries[0]
        parent = self.parent_for(source)
        group = [r for r in records if r['sources'] and
                 all(self.parent_for(s) == parent for s in r['sources'])]
        if any(not record['owned'] for record in group):
            raise RuntimeError('Existing owner manages a DualSense source; preserving its outputs')
        discovered = {s for record in group for s in record['sources']}
        if not self.required_for(source).issubset(discovered):
            return False
        if self.plan is None and any(not record.get('targets') for record in group):
            # Initial default target creation is also asynchronous. An empty
            # list here is not yet acknowledgment of our null-output request.
            return False
        plan = (primary['path'], tuple(sorted(record['path'] for record in group)))
        if plan != self.plan:
            self.companions = set(plan[1]) - {primary['path']}
            # Recreate even the primary: another duplicate may have won kernel
            # registration. Changing only siblings does not re-probe that pad.
            self.plan = plan
            self.binding_attempts = 0
            self.drain(group)
            return False
        if self.phase == 'failed':
            raise RuntimeError(self.failure)
        if self.phase == 'draining':
            # SetTargetDevices returns before asynchronous device teardown ends.
            # Both D-Bus target removal and all UHID roots must acknowledge it.
            if any(record.get('targets') != [] for record in group) or self.virtual_devices():
                if self.clock() - self.drain_started >= self.drain_timeout:
                    self.fail('PlayStation output drain timed out; no replacement pad was created')
                return False
            self.phase = 'binding'
            self.binding_started = self.clock()
            self.binding_attempts += 1
            try:
                self.set_targets(primary['path'], ['ds5', 'mouse', 'keyboard'])
            except Exception as error:
                self.fail(f'PlayStation output binding request failed: {error}')
            return False
        if not self.pad_ready():
            if self.phase == 'ready':
                self.phase = 'binding'
                self.binding_started = self.clock()
            elif self.clock() - self.binding_started >= self.binding_timeout:
                if self.binding_attempts >= self.max_binding_attempts:
                    self.fail(f'PlayStation output failed after {self.binding_attempts} binding attempts')
                self.drain(group)
            return False
        self.phase = 'ready'
        return True
