#!/usr/bin/env python3
"""Bounded file ownership journal used by HSTN installation phases."""
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile


def safe_parents(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(c in str(path) for c in '\n\r\x00'):
        raise RuntimeError(f'Invalid installation path: {path}')
    for parent in reversed(path.parents):
        if parent.is_symlink():
            raise RuntimeError(f'Refusing symlink parent: {parent}')
        if parent.exists() and not parent.is_dir():
            raise RuntimeError(f'Parent is not a directory: {parent}')


def file(data, mode=0o644):
    return {'kind': 'file', 'data': base64.b64encode(data).decode(), 'mode': mode}


def validate(value):
    if value is None:
        return
    if not isinstance(value, dict):
        raise RuntimeError('Invalid file snapshot')
    if value.get('kind') == 'file' and set(value) == {'kind', 'data', 'mode'}:
        if type(value['mode']) is not int or not 0 <= value['mode'] <= 0o777:
            raise RuntimeError('Invalid file mode')
        base64.b64decode(value['data'], validate=True)
    elif value.get('kind') == 'symlink' and set(value) == {'kind', 'target'}:
        if not isinstance(value['target'], str) or '\0' in value['target']:
            raise RuntimeError('Invalid symlink target')
    else:
        raise RuntimeError('Invalid file snapshot')


def snapshot(path):
    path = Path(path)
    safe_parents(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return {'kind': 'symlink', 'target': os.readlink(path)}
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f'Refusing non-file: {path}')
    return file(path.read_bytes(), stat.S_IMODE(info.st_mode))


def atomic(path, data, mode):
    path = Path(path)
    safe_parents(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def restore(path, value):
    path = Path(path)
    safe_parents(path)
    validate(value)
    if value is None:
        path.unlink(missing_ok=True)
        if path.parent.exists():
            sync_directory(path.parent)
    elif value['kind'] == 'file':
        atomic(path, base64.b64decode(value['data']), value['mode'])
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.hstn-link-', dir=path.parent) as folder:
            temporary = Path(folder)/'link'
            temporary.symlink_to(value['target'])
            os.replace(temporary, path)
        sync_directory(path.parent)


class Store:
    def __init__(self, path, allowed_paths):
        self.path = Path(path)
        self.allowed = {str(Path(p)) for p in allowed_paths}
        self.state = {'version': 1, 'files': {}, 'metadata': {}}
        self.lock = None

    def read(self):
        """Validate an existing record without creating a lock or directory."""
        safe_parents(self.path)
        if self.path.is_symlink():
            raise RuntimeError('Installation record must not be a symlink')
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        if self.state.get('version') != 1 or not isinstance(self.state.get('files'), dict):
            raise RuntimeError('Unsupported installation record')
        self.state.setdefault('metadata', {})
        if not isinstance(self.state['metadata'], dict):
            raise RuntimeError('Invalid installation metadata')
        for name, record in self.state['files'].items():
            if name not in self.allowed:
                raise RuntimeError(f'Unrecognized ownership path: {name}')
            if not isinstance(record, dict) or 'installed' not in record or 'previous' not in record:
                raise RuntimeError('Invalid ownership record')
            for key in ('installed', 'previous', 'pending'):
                if key in record:
                    validate(record[key])
        return self

    def __enter__(self):
        safe_parents(self.path)
        if self.path.is_symlink():
            raise RuntimeError('Installation record must not be a symlink')
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.path.with_suffix('.lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, 'r+')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self.read()
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError('Another installation is in progress') from None
        except BaseException:
            self.lock.close()
            raise

    def __exit__(self, *args):
        self.lock.close()

    def save(self):
        atomic(self.path, (json.dumps(self.state, indent=2) + '\n').encode(), 0o600)

    def check(self, files):
        for path, value in files.items():
            if str(path) not in self.allowed:
                raise RuntimeError(f'Unrecognized ownership path: {path}')
            validate(value)
            current = snapshot(path)
            record = self.state['files'].get(str(path))
            if record and current not in (record['installed'], record['previous'], record.get('pending', record['installed'])):
                raise RuntimeError(f'Preserving edited file: {path}')

    def apply(self, files):
        self.check(files)
        for path, value in files.items():
            key = str(path)
            current = snapshot(path)
            record = self.state['files'].setdefault(key, {'previous': current, 'installed': current})
            record['pending'] = value
            self.save()
            if current != value:
                restore(path, value)
            record['installed'] = value
            record.pop('pending', None)
            self.save()

    def remove(self, paths=None):
        conflicts = []
        selected = {str(p) for p in paths} if paths is not None else None
        for key, record in list(self.state['files'].items()):
            if selected is not None and key not in selected:
                continue
            path = Path(key)
            current = snapshot(path)
            if current == record['installed'] or ('pending' in record and current == record['pending']):
                restore(path, record['previous'])
            elif current != record['previous']:
                conflicts.append(key)
                continue
            del self.state['files'][key]
            self.save()
        return conflicts

    def status(self):
        return {key: 'owned' if snapshot(Path(key)) == value['installed'] else 'changed'
                for key, value in self.state['files'].items()}
