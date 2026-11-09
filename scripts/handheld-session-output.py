"""Reversible Heroic browser compatibility for a native Go S Deck HID output."""
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

COMPOSITE = 'org.shadowblip.Input.CompositeDevice'
TARGET = 'org.shadowblip.Input.Target'
JOURNAL = 'hstn-handheld-output.json'


def heroic_targets(original):
    """Only replace the known native Deck/keyboard/mouse combination."""
    for deck in ('deck', 'deck-uhid'):
        if sorted(original) == sorted((deck, 'keyboard', 'mouse')):
            return ['xbox-elite' if kind == deck else kind for kind in original]
    return None


class OutputLease:
    def __init__(self, runtime, *, get_property, set_targets, exists, supported,
                 clock=time.monotonic, sleep=time.sleep):
        self.runtime = Path(runtime)
        self.path = self.runtime / JOURNAL
        self.get = get_property
        self.set = set_targets
        self.exists = exists
        self.supported = supported
        self.clock, self.sleep = clock, sleep
        self.active = None

    def types(self, path):
        return [self.get(target, TARGET, 'DeviceType')
                for target in self.get(path, COMPOSITE, 'TargetDevices')]

    def wait(self, path, expected):
        deadline = self.clock() + 5
        while self.clock() < deadline:
            try:
                if sorted(self.types(path)) == sorted(expected):
                    return
            except (RuntimeError, OSError):
                pass  # Target DBus objects are replaced asynchronously.
            self.sleep(.1)
        raise RuntimeError('Timed out waiting for the handheld controller output')

    def read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 16384):
                raise RuntimeError('Untrusted handheld output recovery record')
            record = json.load(stream)
        if (not isinstance(record, dict) or record.get('version') != 1
                or not isinstance(record.get('path'), str)
                or not re.fullmatch(r'/org/shadowblip/InputPlumber/CompositeDevice[0-9]+', record['path'])
                or not isinstance(record.get('sources'), list)
                or not all(isinstance(source, str) for source in record['sources'])
                or not isinstance(record.get('original'), list)
                or not all(isinstance(kind, str) for kind in record['original'])
                or heroic_targets(record['original']) != record.get('applied')):
            raise RuntimeError('Invalid handheld output recovery record')
        return record

    def write(self, record):
        info = self.runtime.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise RuntimeError('Untrusted handheld output runtime directory')
        fd, temporary = tempfile.mkstemp(prefix='.hstn-output-', dir=self.runtime)
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def acquire(self, path, sources):
        if self.active:
            if self.active != path or sorted(self.types(path)) != sorted(self.read()['applied']):
                raise RuntimeError('Heroic handheld output changed externally')
            return
        if self.path.exists() or self.path.is_symlink():
            raise RuntimeError('Handheld output recovery is required before another lease')
        if not self.supported(sources) or self.get(path, COMPOSITE, 'InterceptMode') != 0:
            raise RuntimeError('Heroic compatibility requires an idle verified Go S controller')
        original = self.types(path)
        applied = heroic_targets(original)
        if applied is None:
            return  # Existing Xbox/custom outputs remain unchanged.
        record = {'version': 1, 'path': path, 'sources': sorted(sources),
                  'original': original, 'applied': applied}
        self.write(record)
        self.active = path
        self.set(path, applied)
        self.wait(path, applied)

    def recover(self, *, owned=False):
        record = self.read()
        if record is None:
            return
        path = record['path']
        if not self.exists(path):
            self.path.unlink()
            return  # Removing the composite also removed its temporary output.
        sources = self.get(path, COMPOSITE, 'SourceDevicePaths')
        if sorted(sources) != record['sources'] or not self.supported(sources):
            raise RuntimeError('Handheld controller sources changed; output recovery retained')
        if not owned and self.get(path, COMPOSITE, 'InterceptMode') != 0:
            raise RuntimeError('An input owner is active; handheld output recovery retained')
        current = self.types(path)
        if sorted(current) == sorted(record['applied']):
            self.set(path, record['original'])
            self.wait(path, record['original'])
        elif sorted(current) != sorted(record['original']):
            raise RuntimeError('Handheld outputs changed externally; recovery retained')
        self.path.unlink()
        self.active = None
