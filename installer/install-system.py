#!/usr/bin/env python3
"""Narrow root-owned HSTN system phase. Never read user installation records."""
import argparse
import configparser
import importlib.util
import json
import os
import shlex
from pathlib import Path
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
UNIT = 'session-switch-input-guard.service'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/('installer' if name in ('install-hstn', 'install-system', 'install-state', 'clean-installation', 'remove-launcher-assets') else 'scripts')/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = load('install-state')


def command(args, check=True, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=150)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'Failed: {args}')
    return result


def record_path(root):
    return Path(root)/'var/lib/hstn/system-install.json'


def guard_path(root):
    # Fedora Atomic deliberately aliases /usr/local to /var/usrlocal. Resolve
    # this platform base, while still rejecting symlinks below it.
    return (Path(root)/'usr/local').resolve()/'libexec/session-switch-input-guard.py'


def trusted_record(root=Path('/'), owner_uid=0):
    path = record_path(root)
    state.safe_parents(path)
    # The journal can restore root-executed files. Never accept one planted in
    # a foreign-owned directory, even when its individual paths are allowlisted.
    for parent in [path.parent, *path.parent.parents]:
        if parent == Path(root):
            break
        if parent.exists():
            info = parent.lstat()
            forbidden = 0o077 if parent == path.parent else 0o022
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid or info.st_mode & forbidden:
                raise RuntimeError(f'Untrusted system record directory ownership: {parent}')
    for candidate in (path, path.with_suffix('.lock'), path.with_name('cleanup.json'), path.with_name('cleanup.lock')):
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o077:
                raise RuntimeError(f'System installation record must be private and trusted: {candidate}')


def trusted_destinations(paths):
    for path in paths:
        state.safe_parents(path)
        for parent in path.parents:
            if parent.exists():
                info = parent.lstat()
                if info.st_uid != 0 or info.st_mode & 0o022:
                    raise RuntimeError(f'Untrusted system destination parent: {parent}')
        if path.is_symlink():
            raise RuntimeError(f'Remove or resolve the pre-existing system symlink before installation: {path}')
        if path.exists():
            info = path.lstat()
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise RuntimeError(f'Untrusted system destination: {path}')


def system_files(source, root=Path('/'), package=False):
    source, root = Path(source), Path(root)
    directories = load('mechanic').session_dirs(root)
    for name in ('/etc/wayland-sessions', '/usr/local/share/wayland-sessions', '/usr/share/wayland-sessions'):
        if name not in directories:
            directories.append(name)
    if any(c in ','.join(directories) for c in '\n\r\x00'):
        raise RuntimeError('Invalid SDDM session directory')
    files = {
        root/'etc/wayland-sessions/gamescope-session-heroic.desktop': state.file(
            b'[Desktop Entry]\nName=Heroic Gaming Mode\nComment=Heroic Console Mode running in Gamescope\n'
            b'Exec=/usr/bin/gamescope-session-plus heroic\nType=Application\nDesktopNames=gamescope\n'),
        root/'etc/sddm.conf.d/zzzzz-hstn-sessions.conf': state.file(
            ('[Wayland]\nSessionDir=' + ','.join(directories) + '\n').encode()),
    }
    if not package:
        files[guard_path(root)] = state.file(
            (source/'scripts/session-switch-input-guard.py').read_bytes(), 0o755)
        files[root/'etc/systemd/system'/UNIT] = state.file((source/'templates/systemd'/UNIT).read_bytes())
    return files


def check_sddm_precedence(root=Path('/')):
    # SDDM's main config overrides all snippets. Refuse an ineffective install.
    import configparser
    main = Path(root)/'etc/sddm.conf'
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read(main)
    if parser.has_option('Wayland', 'SessionDir'):
        if '/etc/wayland-sessions' not in [p.strip() for p in parser.get('Wayland', 'SessionDir').split(',')]:
            raise RuntimeError('Main /etc/sddm.conf overrides SessionDir; add /etc/wayland-sessions there before installing')


def ready():
    return load('input-guard-status').permanent_guard_active()


def vendor_timeout_policy(path, root):
    """Accept only the trusted vendor-wide Fedora timeout policy, never Exec*."""
    path = Path(path)
    if path.parent != Path(root)/'usr/lib/systemd/system/service.d' or path.suffix != '.conf':
        return False
    trusted_destinations([path])
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read_string(path.read_text())
    except (OSError, configparser.Error):
        return False
    return (not parser.defaults() and parser.sections() == ['Service']
            and dict(parser.items('Service')) == {'TimeoutStopFailureMode': 'abort'})


def verify_service_layout(root, run, package=False, installed=False):
    expected = Path(root)/('usr/lib/systemd/system' if package else 'etc/systemd/system')/UNIT
    dropins = run(['/usr/bin/systemctl', 'show', UNIT, '--property=DropInPaths', '--value'], check=False).stdout.strip()
    rejected = [path for path in shlex.split(dropins) if not vendor_timeout_policy(path, root)]
    if rejected:
        raise RuntimeError('Guard service drop-ins require explicit administrator review/removal before HSTN setup: ' + ', '.join(rejected))
    fragment = run(['/usr/bin/systemctl', 'show', UNIT, '--property=FragmentPath', '--value'], check=False).stdout.strip()
    if fragment and Path(fragment) != expected:
        raise RuntimeError(f'Unexpected guard service fragment/shadow: {fragment}; expected {expected}')
    if installed and not fragment:
        raise RuntimeError('Guard service fragment is missing after daemon-reload')
    if package and Path(root) == Path('/'):
        # A local unit would shadow the packaged service even before reload.
        for base in ('etc/systemd/system', 'run/systemd/system'):
            shadow = Path(root)/base/UNIT
            if shadow.exists() or shadow.is_symlink():
                raise RuntimeError(f'Local guard unit shadows the native package: {shadow}')
        trusted_destinations([expected, Path(root)/'usr/libexec/session-switch-input-guard.py'])


def service_state(run):
    enabled = run(['/usr/bin/systemctl', 'is-enabled', UNIT], check=False).stdout.strip()
    active = run(['/usr/bin/systemctl', 'is-active', UNIT], check=False).stdout.strip()
    if enabled not in ('enabled', 'disabled', 'static', 'indirect', 'not-found'):
        raise RuntimeError(f'Unsupported guard enablement state: {enabled}; resolve it before installation')
    if active not in ('active', 'inactive', 'failed', 'unknown'):
        raise RuntimeError(f'Unsupported guard activity state: {active}')
    return {'enabled': enabled == 'enabled', 'active': active == 'active'}


def apply_system(source, root=Path('/'), run=command, package=False):
    root = Path(root)
    check_sddm_precedence(root)
    files = system_files(source, root, package)
    if root == Path('/'):
        trusted_record(root)
        trusted_destinations(files)
        if package:
            expected = (Path(source)/'templates/systemd'/UNIT).read_bytes().replace(
                b'/usr/local/libexec/session-switch-input-guard.py', b'/usr/libexec/session-switch-input-guard.py')
            if (root/'usr/lib/systemd/system'/UNIT).read_bytes() != expected or (root/'usr/libexec/session-switch-input-guard.py').read_bytes() != (Path(source)/'scripts/session-switch-input-guard.py').read_bytes():
                raise RuntimeError('Packaged guard unit/helper differs from the release; reinstall the native package before setup')
    verify_service_layout(root, run, package)
    with state.Store(record_path(root), files) as store:
        store.check(files)
        metadata = store.state['metadata']
        if metadata.get('removed') and not store.state['files']:
            metadata.clear()
        if 'service' not in metadata:
            metadata['service'] = service_state(run)
            metadata['package'] = package
            store.save()
        elif metadata.get('package', False) != package:
            raise RuntimeError('Remove the previous system installation before changing installation methods')
        changed_guard = any(state.snapshot(p) != value for p, value in files.items()
                            if 'libexec' in str(p) or p.name == UNIT)
        if changed_guard and run(['/usr/bin/systemctl', 'is-active', UNIT], check=False).stdout.strip() == 'active':
            run(['/usr/bin/systemctl', 'stop', UNIT])
        store.apply(files)
        if '/etc/wayland-sessions' not in load('mechanic').session_dirs(root):
            raise RuntimeError('Effective SDDM SessionDir still excludes the Heroic session; restore or revise higher-priority configuration')
        run(['/usr/bin/systemctl', 'daemon-reload'])
        verify_service_layout(root, run, package, installed=True)
        run(['/usr/bin/systemctl', 'enable', UNIT])
        run(['/usr/bin/systemctl', 'start', UNIT])
        if not ready():
            raise RuntimeError('Guard did not publish trusted readiness; keep the installation record and retry after inspecting its journal')
        metadata['complete'] = True
        store.save()


def remove_system(root=Path('/'), run=command):
    root = Path(root)
    path = record_path(root)
    if root == Path('/'):
        trusted_record(root)
    if not path.exists():
        return []
    # Allowed paths are fixed; root never accepts user-supplied restore targets.
    allowed = [guard_path(root), root/'etc/systemd/system'/UNIT,
               root/'etc/wayland-sessions/gamescope-session-heroic.desktop',
               root/'etc/sddm.conf.d/zzzzz-hstn-sessions.conf']
    if root == Path('/'):
        trusted_destinations(allowed)
    with state.Store(path, allowed) as store:
        metadata = store.state['metadata']
        if metadata.get('removed') and not store.state['files']:
            return []
        changed = [p for p, status in store.status().items() if status != 'owned'
                   and state.snapshot(Path(p)) != store.state['files'][p]['previous']
                   and state.snapshot(Path(p)) != store.state['files'][p].get('pending')]
        if changed:
            return changed
        prior = store.state['metadata'].get('service', {'active': False, 'enabled': False})
        if not store.state['files']:
            # Interrupted before the first file write: only a previously active
            # guard might have been stopped; never stop a nonexistent unit.
            if prior['active']:
                run(['/usr/bin/systemctl', 'start', UNIT])
            metadata['removed'] = True
            store.save()
            return []
        current_active = run(['/usr/bin/systemctl', 'is-active', UNIT], check=False).stdout.strip()
        if current_active in ('active', 'activating', 'deactivating', 'reloading', 'failed'):
            run(['/usr/bin/systemctl', 'stop', UNIT])
        current_enabled = run(['/usr/bin/systemctl', 'is-enabled', UNIT], check=False).stdout.strip()
        if not prior['enabled'] and current_enabled in ('enabled', 'enabled-runtime'):
            run(['/usr/bin/systemctl', 'disable', UNIT])
        conflicts = store.remove()
        run(['/usr/bin/systemctl', 'daemon-reload'])
        if prior['enabled']:
            run(['/usr/bin/systemctl', 'enable', UNIT])
        if prior['active']:
            run(['/usr/bin/systemctl', 'start', UNIT])
        store.state['metadata']['removed'] = not conflicts
        store.save()
        return conflicts


def legacy_system_files(source, root=Path('/'), check_trust=True):
    """Fixed legacy paths only; never infer root deletion targets from user data."""
    source, root = Path(source), Path(root)
    candidates = {
        guard_path(root): ('helper', (source/'scripts/session-switch-input-guard.py').read_bytes()),
        root/'etc/systemd/system'/UNIT: ('unit', (source/'templates/systemd'/UNIT).read_bytes()),
        root/'etc/wayland-sessions/gamescope-session-heroic.desktop': ('session', None),
        root/'usr/local/share/wayland-sessions/gamescope-session-heroic.desktop': ('session', None),
        root/'etc/sddm.conf.d/zzzz-gamescope-sessions.conf': ('sddm', None),
        root/'etc/sddm.conf.d/zzzzz-hstn-sessions.conf': ('sddm', None),
        root/'etc/zz-holo-autologin.conf.bak': ('inactive', None),
        root/'etc/zzzz-session-test.conf.disabled': ('inactive', None),
        root/'etc/zzzz-session-switcher.conf.disabled': ('inactive', None),
        root/'etc/zzt-holo-temp-login.conf.disabled': ('inactive', None),
    }
    # Only the documented /usr/local platform alias is resolved.
    local_entry = root/'usr/local/share/wayland-sessions/gamescope-session-heroic.desktop'
    candidates.pop(local_entry)
    candidates[(root/'usr/local').resolve()/'share/wayland-sessions/gamescope-session-heroic.desktop'] = ('session', None)
    files = {}
    for path, (kind, expected) in candidates.items():
        if not path.exists() and not path.is_symlink(): continue
        state.safe_parents(path)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f'Preserving unrecognized legacy root path: {path}')
        if check_trust and root == Path('/'): trusted_destinations([path])
        value = path.read_bytes()
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        matches = value == expected if expected is not None else False
        if kind == 'unit':
            import re
            matches = re.sub(rb'^Description=.*$', b'Description=HSTN', value, flags=re.M) == re.sub(
                rb'^Description=.*$', b'Description=HSTN', expected, flags=re.M)
        elif kind in ('session', 'sddm', 'inactive'):
            parser.read_string(value.decode())
            if kind == 'session':
                matches = (parser.sections() == ['Desktop Entry'] and not parser.defaults()
                    and parser.get('Desktop Entry', 'Name', fallback='') == 'Heroic Gaming Mode'
                    and parser.get('Desktop Entry', 'Exec', fallback='') == '/usr/bin/gamescope-session-plus heroic'
                    and set(parser['Desktop Entry']) <= {'Name', 'Comment', 'Exec', 'Type', 'DesktopNames'})
            elif kind == 'sddm':
                matches = (parser.sections() == ['Wayland'] and not parser.defaults()
                    and set(parser['Wayland']) == {'SessionDir'}
                    and parser.get('Wayland', 'SessionDir').replace(' ', '') == '/etc/wayland-sessions,/usr/local/share/wayland-sessions,/usr/share/wayland-sessions')
            else:
                matches = (parser.sections() == ['Autologin'] and not parser.defaults()
                    and set(parser['Autologin']) <= {'Session', 'User', 'Relogin'} and parser.get('Autologin', 'Session', fallback='') in
                    ('', 'gamescope-session-ogui-steam.desktop', 'gamescope-session-steam.desktop', 'gamescope-session-heroic.desktop'))
        if not matches:
            raise RuntimeError(f'Preserving unrecognized or edited legacy system file: {path}')
        files[path] = None
    return files


def prune_system_records(root=Path('/')):
    root = Path(root)
    if root == Path('/'): trusted_record(root)
    path = record_path(root)
    if path.exists():
        record = json.loads(path.read_text())
        if record.get('files') or not record.get('metadata', {}).get('removed'):
            raise RuntimeError('System ownership remains unresolved; keep recovery records')
        path.unlink()
    path.with_suffix('.lock').unlink(missing_ok=True)
    try: path.parent.rmdir()
    except OSError: pass


def clean_system(source, root=Path('/'), run=command):
    root = Path(root)
    if root == Path('/'):
        trusted_record(root)
    # Validate all targets before stopping the service or deleting anything.
    files = legacy_system_files(source, root)
    verify_service_layout(root, run)
    active = run(['/usr/bin/systemctl', 'is-active', UNIT], check=False).stdout.strip()
    if active in ('active', 'activating', 'deactivating', 'failed'):
        run(['/usr/bin/systemctl', 'stop', UNIT])
    enabled = run(['/usr/bin/systemctl', 'is-enabled', UNIT], check=False).stdout.strip()
    if enabled in ('enabled', 'enabled-runtime'):
        run(['/usr/bin/systemctl', 'disable', UNIT])
    # A retained guard journal is recovery data, not disposable install state.
    guard_journal = root/'run/session-switch-input-guard/backups.json'
    if guard_journal.exists() and json.loads(guard_journal.read_text()):
        raise RuntimeError('Input guard recovery journal remains after stop; inspect/recover it before clean-slate removal')
    journal = record_path(root).with_name('cleanup.json')
    allowed = set(files)
    if journal.exists():
        prior = json.loads(journal.read_text())
        for name in prior.get('files', {}):
            # Entries can only be the fixed paths that this function knows.
            known = {guard_path(root), root/'etc/systemd/system'/UNIT,
                root/'etc/wayland-sessions/gamescope-session-heroic.desktop',
                (root/'usr/local').resolve()/'share/wayland-sessions/gamescope-session-heroic.desktop',
                root/'etc/sddm.conf.d/zzzz-gamescope-sessions.conf', root/'etc/sddm.conf.d/zzzzz-hstn-sessions.conf',
                *(root/'etc'/n for n in ('zz-holo-autologin.conf.bak', 'zzzz-session-test.conf.disabled',
                    'zzzz-session-switcher.conf.disabled', 'zzt-holo-temp-login.conf.disabled'))}
            if Path(name) not in known: raise RuntimeError('Unrecognized root cleanup recovery path')
            allowed.add(Path(name))
    with state.Store(journal, allowed) as store:
        store.apply({path: None for path in allowed})
    run(['/usr/bin/systemctl', 'daemon-reload'])
    runtime = root/'run/session-switch-input-guard'
    for name in ('backups.json', 'active', 'lock'):
        path = runtime/name
        if path.exists():
            if root == Path('/'): trusted_destinations([path])
            path.unlink()
    try: runtime.rmdir()
    except OSError: pass
    for name in ('system-install.json', 'system-install.lock', 'cleanup.json', 'cleanup.lock'):
        path = record_path(root).with_name(name)
        if path.is_symlink(): raise RuntimeError(f'Untrusted root cleanup record: {path}')
        path.unlink(missing_ok=True)
    try: record_path(root).parent.rmdir()
    except OSError: pass


def trusted_stage():
    # All executed modules and payloads must be copied to a root-private stage.
    for name in ('installer/install-system.py', 'installer/install-state.py', 'scripts/mechanic.py',
                 'scripts/input-guard-status.py', 'scripts/session-switch-input-guard.py',
                 'templates/systemd/session-switch-input-guard.service'):
        path = ROOT/name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError(f'Untrusted staged payload: {path}')
        for parent in [path.parent, *path.parent.parents]:
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise RuntimeError(f'Untrusted stage directory: {parent}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'uninstall', 'clean-slate'))
    parser.add_argument('--package', action='store_true')
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise RuntimeError('System phase requires root; use the user installer to stage it')
        trusted_stage()
        if args.package and not Path('/usr/lib/hstn/PACKAGE-MANAGED').is_file():
            raise RuntimeError('Native package marker is missing')
        if args.action == 'clean-slate':
            if args.package or Path('/usr/lib/hstn/PACKAGE-MANAGED').exists():
                raise RuntimeError('Remove native HSTN packages through the package manager before clean-slate cleanup')
            conflicts = remove_system()
            if not conflicts: clean_system(ROOT)
        else:
            conflicts = remove_system() if args.action == 'uninstall' else (apply_system(ROOT, package=args.package) or [])
            if args.action == 'uninstall' and not conflicts:
                prune_system_records()
        if conflicts:
            raise RuntimeError('Preserved edited system files: ' + ', '.join(conflicts))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'HSTN system installation: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
