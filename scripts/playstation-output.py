#!/usr/bin/env python3
"""Single DualSense output for an overlay-owned, temporary controller group."""
import os
from pathlib import Path
import time
import importlib.util

spec = importlib.util.spec_from_file_location('supported_controllers', Path(__file__).with_name('supported-controllers.py'))
controllers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controllers)


def parent_for(source):
    return controllers.supported_parent(source)


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
                 drain_timeout=15, primary_source=None, targets=None):
        self.set_targets = set_targets
        self.primary_source = primary_source or (lambda source: source.startswith('/dev/hidraw'))
        self.targets = targets or ['ds5', 'mouse', 'keyboard']
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
            self.fail(f'Controller output drain failed: {error}')

    def fail(self, message):
        self.phase = 'failed'
        self.failure = message
        raise RuntimeError(message)

    def update(self, records):
        primaries = [(record, source) for record in records for source in record['sources']
                     if self.primary_source(source) and self.parent_for(source)]
        if not primaries:
            return self.plan is None
        if len(primaries) != 1:
            raise RuntimeError('Controller output requires exactly one primary physical source per controller group')
        primary, source = primaries[0]
        parent = self.parent_for(source)
        group = [r for r in records if r['sources'] and
                 all(self.parent_for(s) == parent for s in r['sources'])]
        if any(not record['owned'] for record in group):
            raise RuntimeError('Existing owner manages a supported source; preserving its outputs')
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
                    self.fail('Controller output drain timed out; no replacement pad was created')
                return False
            self.phase = 'binding'
            self.binding_started = self.clock()
            self.binding_attempts += 1
            try:
                self.set_targets(primary['path'], self.targets)
            except Exception as error:
                self.fail(f'Controller output binding request failed: {error}')
            return False
        if not self.pad_ready():
            if self.phase == 'ready':
                self.phase = 'binding'
                self.binding_started = self.clock()
            elif self.clock() - self.binding_started >= self.binding_timeout:
                if self.binding_attempts >= self.max_binding_attempts:
                    self.fail(f'Controller output failed after {self.binding_attempts} binding attempts')
                self.drain(group)
            return False
        self.phase = 'ready'
        return True


def device_ready(device):
    """Validate one assigned UHID output, without counting other controllers."""
    parent = Path(device)
    try:
        if (parent/'driver').resolve(strict=True).name != 'playstation':
            return False
        return any((node.parent/'name').read_text().strip().endswith('Wireless Controller')
                   and os.access('/dev/input/' + node.name, os.R_OK)
                   for node in parent.glob('input/input*/event*'))
    except OSError:
        return False


class PlayStationOutputs:
    """One output state machine per physical controller; serialize UHID binding."""
    def __init__(self, set_targets, *, parent_for=parent_for, required_for=required_for,
                 virtual_devices=virtual_devices, device_ready=device_ready,
                 factory=PlayStationOutput, primary_source=None):
        self.set_targets = set_targets
        self.parent_for = parent_for
        self.required_for = required_for
        self.virtual_devices = virtual_devices
        self.device_ready = device_ready
        self.factory = factory
        self.primary_source = primary_source or (lambda source: source.startswith('/dev/hidraw'))
        self.controllers = {}
        self.outputs = {}
        self.companions = set()
        self.ready_paths = set()
        self.failures = {}
        self.phase = 'discover'

    def devices_for(self, parent):
        others = set().union(*(nodes for key, nodes in self.outputs.items() if key != parent))
        return set(self.virtual_devices()) - others

    def ready_for(self, parent):
        nodes = self.devices_for(parent)
        if len(nodes) != 1:
            return False
        self.outputs[parent] = nodes
        return self.device_ready(next(iter(nodes)))

    def update(self, records):
        groups = {}
        for record in records:
            parents = {self.parent_for(source) for source in record['sources']}
            if len(parents) == 1 and None not in parents:
                groups.setdefault(parents.pop(), []).append(record)
        groups = {parent: group for parent, group in groups.items()
                  if any(self.primary_source(source) for record in group for source in record['sources'])}
        for parent in set(self.controllers) - set(groups):
            del self.controllers[parent]
            self.outputs.pop(parent, None)
            self.failures.pop(parent, None)
        # Drain every newly discovered group's defaults before assigning any
        # replacement. Other controllers' assigned UHID roots remain untouched.
        for parent, group in groups.items():
            if parent not in self.controllers:
                self.controllers[parent] = self.factory(
                    self.set_targets, parent_for=self.parent_for, required_for=self.required_for,
                    virtual_devices=lambda parent=parent: self.devices_for(parent),
                    pad_ready=lambda parent=parent: self.ready_for(parent))
            state = self.controllers[parent]
            if state.plan is None and parent not in self.failures:
                try:
                    state.update(group)
                except RuntimeError as error:
                    self.failures[parent] = str(error)
        self.companions = set().union(*(state.companions for state in self.controllers.values()))
        self.ready_paths = set()
        pending = False
        for parent, state in self.controllers.items():
            if parent in self.failures:
                continue
            if state.phase == 'ready':
                # Existing controllers can keep working while another binds.
                same_group = state.plan and state.plan[1] == tuple(sorted(
                    record['path'] for record in groups[parent]))
                if (same_group and self.outputs.get(parent)
                        and all(self.device_ready(node) for node in self.outputs[parent])):
                    self.ready_paths.update(record['path'] for record in groups[parent])
                    continue
                self.outputs.pop(parent, None)
            if pending:
                continue
            try:
                ready = state.update(groups[parent])
            except RuntimeError as error:
                self.failures[parent] = str(error)
                continue
            if ready:
                self.ready_paths.update(record['path'] for record in groups[parent])
            else:
                pending = True
        self.phase = 'partial' if self.failures else ('initializing' if pending else 'ready')
        return bool(self.controllers) and not pending and not self.failures
