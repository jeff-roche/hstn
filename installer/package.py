#!/usr/bin/env python3
"""Build reproducible HSTN archives or stage a native package using DESTDIR."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def version(root):
    value = (root/'VERSION').read_text().strip()
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9]+)*', value):
        raise ValueError('Invalid release version')
    return value


def inventory(root):
    root = Path(root)
    files = json.loads((root/'installer/files.json').read_text())
    manifest = json.loads((root/'manifest.json').read_text())
    files += [str(PurePosixPath(manifest['assets_dir'])/asset)
              for dest in manifest['destinations'].values() for asset in dest['images'].values()]
    for name in files:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or str(path) != name:
            raise ValueError(f'Invalid package path: {name}')
        source = root/name
        if source.is_symlink() or not source.is_file() or root.resolve() not in source.resolve().parents:
            raise ValueError(f'Missing or unsafe package file: {name}')
    return sorted(set(files))


def file_mode(name):
    return 0o755 if name.startswith('scripts/') or name in (
        'installer/install.sh', 'installer/install.py', 'src/session-overlay.py') else 0o644


def build(root, output):
    root, output = Path(root), Path(output)
    names = inventory(root)
    prefix = 'hstn-' + version(root)
    output.mkdir(parents=True, exist_ok=True)
    path = output/(prefix + '.tar.gz')
    with path.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for name in names:
                data = (root/name).read_bytes()
                entry = tarfile.TarInfo(prefix + '/' + name)
                entry.size = len(data)
                entry.mode = file_mode(name)
                entry.mtime = 0
                archive.addfile(entry, io.BytesIO(data))
    (output/'SHA256SUMS').write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n')
    return path


def stage(root, destination):
    root, destination = Path(root), Path(destination)
    names = inventory(root)
    for name in names:
        path = destination/'usr/lib/hstn'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root/name).read_bytes())
        path.chmod(file_mode(name))
    command = destination/'usr/bin/hstn'
    command.parent.mkdir(parents=True, exist_ok=True)
    command.symlink_to('../lib/hstn/scripts/hstn')
    guard = destination/'usr/libexec/session-switch-input-guard.py'
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_bytes((root/'scripts/session-switch-input-guard.py').read_bytes())
    guard.chmod(0o755)
    unit = destination/'usr/lib/systemd/system/session-switch-input-guard.service'
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text((root/'templates/systemd/session-switch-input-guard.service').read_text().replace(
        '/usr/local/libexec/session-switch-input-guard.py', '/usr/libexec/session-switch-input-guard.py'))
    unit.chmod(0o644)
    (destination/'usr/lib/hstn/PACKAGE-MANAGED').write_text('Native package: use your package manager for upgrades/removal.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--destdir', type=Path, help='Stage native-package files; never controls services')
    args = parser.parse_args()
    if args.destdir:
        stage(ROOT, args.destdir)
    else:
        print(build(ROOT, args.output))


if __name__ == '__main__':
    main()
