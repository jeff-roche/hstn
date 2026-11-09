#!/usr/bin/env python3
"""Route each owned controller through its family's virtual gamepad output."""
import importlib.util
import os
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


controllers = load('supported-controllers')
playstation = load('playstation-output')
profiles = load('input-profiles')


def xbox_devices(sysfs=Path('/sys')):
    found = set()
    for node in Path(sysfs).glob('class/input/event*'):
        parent = (node/'device').resolve()
        try:
            identity = dict(line.split('=', 1) for line in (parent/'uevent').read_text().splitlines() if '=' in line)
            if controllers.xbox_output({'virtual': Path(sysfs)/'devices/virtual' in parent.parents,
                                        'identity': identity}):
                found.add(str(parent))
        except OSError:
            pass
    return sorted(found)


def xbox_ready(device):
    return any(os.access('/dev/input/' + event.name, os.R_OK) for event in Path(device).glob('event*'))


def xbox_required(source):
    # Native Bluetooth input comes from HID even if the optional evdev feedback
    # source is absent. The guard reserves all physical siblings independently.
    return {source} if controllers.supported_parent(source) else set()


class ControllerOutputs:
    def __init__(self, set_targets):
        self.sony = playstation.PlayStationOutputs(set_targets)
        self.primary_sources = set()
        def primary(source):
            return source in self.primary_sources

        def factory(set_targets, **kwargs):
            return playstation.PlayStationOutput(set_targets, **kwargs,
                primary_source=primary, targets=['xbox-series', 'mouse', 'keyboard'])

        self.xbox = playstation.PlayStationOutputs(set_targets, required_for=xbox_required,
            virtual_devices=xbox_devices, device_ready=xbox_ready,
            factory=factory, primary_source=primary)
        self.ready_paths = set()
        self.companions = set()
        self.failures = {}
        self.phase = 'discover'

    def update(self, records):
        sony, xbox = [], []
        for record in records:
            if not controllers.supported_sources(record['sources']):
                continue
            profile = controllers.composite_profile(record['sources'])
            if profile and profiles.PROFILES[profile]['output_policy'] == 'preserve':
                continue
            families = {controllers.xbox_source(source) for source in record['sources']}
            if len(families) == 1:
                (xbox if True in families else sony).append(record)
        groups = {}
        for record in xbox:
            for source in record['sources']:
                groups.setdefault(controllers.supported_parent(source), set()).add(source)
        # Native Bluetooth profiles consume HID; xpad and xpadneo can use evdev.
        self.primary_sources = {min(sources, key=lambda source: (not source.startswith('/dev/hidraw'), source))
                                for sources in groups.values()}
        self.sony.update(sony)
        self.xbox.update(xbox)
        self.ready_paths = self.sony.ready_paths | self.xbox.ready_paths
        self.companions = self.sony.companions | self.xbox.companions
        self.failures = {**self.sony.failures, **self.xbox.failures}
        self.phase = ('partial' if self.failures else 'initializing' if any(
            manager.controllers and manager.phase != 'ready' for manager in (self.sony, self.xbox)) else 'ready')
        return bool(self.ready_paths) and self.phase == 'ready'
