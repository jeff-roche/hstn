#!/usr/bin/env python3
"""Explicit legacy HSTN inventory and resumable user asset cleanup."""
import configparser
import importlib.util
import io
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/('installer' if name in ('install-hstn', 'install-system', 'install-state', 'clean-installation', 'remove-launcher-assets') else 'scripts')/f'{name}.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


state = load('install-state')


def templates(root, links):
    root = Path(root)
    result = {name: (root/relative).read_bytes() for name, relative in links.items()}
    for name in ('controller-input-test', 'session-switch-test-game'):
        path = root/'scripts'/name
        if path.exists():
            result[name] = path.read_bytes()
    result['_root'] = str(root.resolve())
    result['_units'] = {name: (root/'templates/systemd'/name).read_bytes() for name in
                        ('session-switch-overlay.service', 'hstn-desktop-overlay.service')}
    result['_sessions'] = {name: (root/'templates/config/gamescope-session-plus/sessions.d'/name).read_bytes()
                           for name in ('steam', 'ogui-steam', 'heroic')}
    return result


def normalized_unit(data):
    data = re.sub(rb'^Description=.*$', b'Description=HSTN', data, flags=re.M)
    return data.replace(b'Conflicts=hstn-desktop-overlay.service\n', b'').replace(
        b'After=hstn-desktop-overlay.service\n', b'')


def recognized_command(path, name, samples, locations, historical=False):
    if path.is_symlink():
        target = path.resolve()
        return (any(base in target.parents for base in (Path(samples['_root']), locations.runtime))
                or target.is_file() and target.read_bytes() == samples[name])
    value = path.read_bytes()
    if value == samples[name]:
        return True
    if historical and value.replace(b'Session Switch', b'HSTN') == samples[name].replace(b'Session Switch', b'HSTN'):
        return True
    if name == 'heroic-gamescope':
        tokens = [b'com.heroicgameslauncher.hgl', b'--console', b'--fullscreen', b'--ozone-platform=x11', b'STEAM_GAME']
        if not historical: tokens.append(b'GAMESCOPECTRL_BASELAYER_APPID')
        return all(token in value for token in tokens)
    if historical and name == 'session-switch':
        return all(token in value for token in (b'gamescope-session-heroic.desktop',
            b'gamescope-session-ogui-steam.desktop', b'SetTemporarySession', b'com.steampowered.SteamOSManager1'))
    if historical and name == 'gamescope-client-with-overlay':
        return all(token in value for token in (b'session-switch-overlay.service', b'wait-controller-isolation.py', b'heroic-window-focus.py'))
    return False


def private_directories(locations):
    base = locations.state.parent.parent
    result = [base/'session-switch', base/'session-switch-backups', locations.state.parent/'doctor']
    if locations.session_runtime is not None:
        result.append(locations.session_runtime/'session-switch-confirmations')
    return tuple(result)


def user_files(locations, samples, legacy=False, handled=None, originals=None):
    files = {}
    handled, originals = handled or {}, originals or {}
    def skip(path):
        return path in handled and state.snapshot(path) == handled[path]
    def unrecognized(path, kind):
        if path in originals and state.snapshot(path) == originals[path]:
            return True
        raise RuntimeError(f'Preserving unrecognized or edited legacy {kind}: {path}')
    if legacy:
        for name in (name for name in samples if not name.startswith('_')):
            path = locations.bin/name
            if path.exists() or path.is_symlink():
                state.safe_parents(path)
                if skip(path): continue
                if not recognized_command(path, name, samples, locations):
                    if unrecognized(path, 'command'): continue
                files[path] = None
            for backup in locations.bin.glob(name + '.*'):
                if re.fullmatch(re.escape(name) + r'\.(?:bak(?:[-.][\w.-]+)?|pre-[\w.-]+|kde-only)', backup.name):
                    state.safe_parents(backup)
                    if not recognized_command(backup, name, samples, locations, historical=True):
                        raise RuntimeError(f'Preserving unrecognized legacy command backup: {backup}')
                    files[backup] = None
        for name, sample in samples['_sessions'].items():
            path = locations.config/'gamescope-session-plus/sessions.d'/name
            if path.exists():
                state.safe_parents(path)
                if skip(path): continue
                value = path.read_bytes()
                if value != sample and not (name == 'heroic' and b'CLIENTCMD="$HOME/.local/bin/heroic-gamescope"' in value):
                    if unrecognized(path, 'session configuration'): continue
                files[path] = None
        for name, sample in samples['_units'].items():
            path = locations.config/'systemd/user'/name
            if path.exists():
                state.safe_parents(path)
                if skip(path): continue
                value = path.read_bytes()
                if normalized_unit(value) != normalized_unit(sample):
                    # Generated Desktop unit has a runtime path and XDG lines.
                    if name != 'hstn-desktop-overlay.service' or b'org.hstn.DesktopOverlay' not in value or b'/prototypes/session-overlay.py" --desktop' not in value:
                        if unrecognized(path, 'user unit'): continue
                files[path] = None
            for backup in path.parent.glob(name + '.bak*'):
                state.safe_parents(backup)
                if backup.is_symlink() or normalized_unit(backup.read_bytes()) != normalized_unit(sample):
                    raise RuntimeError(f'Preserving unrecognized legacy unit backup: {backup}')
                files[backup] = None
        for directory in (locations.desktop, locations.data/'applications', locations.config/'autostart'):
            for path in directory.glob('hstn-*.desktop'):
                state.safe_parents(path)
                if skip(path): continue
                if b'HSTN' not in path.read_bytes():
                    if unrecognized(path, 'Desktop file'): continue
                files[path] = None
        if locations.override.exists():
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read_string(locations.override.read_text())
            section = 'Session Bus Policy'
            if parser.get(section, 'org.freedesktop.Flatpak', fallback=None) == 'talk':
                parser.remove_option(section, 'org.freedesktop.Flatpak')
                if not parser.items(section): parser.remove_section(section)
                output = io.StringIO(); parser.write(output, space_around_delimiters=False)
                files[locations.override] = output.getvalue().encode() if parser.sections() or parser.defaults() else None
    # These directories contain HSTN captures/backups, never launcher libraries.
    for directory in private_directories(locations):
        state.safe_parents(directory)
        if directory.is_symlink():
            raise RuntimeError(f'Preserving symlinked HSTN private directory: {directory}')
        for path in directory.rglob('*'):
            if path.is_file() or path.is_symlink():
                state.safe_parents(path); files[path] = None
    log = locations.state.parent.parent/'heroic-gamescope.log'
    if log.exists(): files[log] = None
    runtime = locations.session_runtime
    if runtime is not None:
        for name in ('hstn-desktop-overlay.env', 'session-switch-overlay.env', 'hstn-overlay.lock'):
            path = runtime/name
            if path.exists() or path.is_symlink():
                state.safe_parents(path); files[path] = None
        for path in runtime.glob('hstn-focus-*.js'):
            if re.fullmatch(r'hstn-focus-[0-9]+\.js', path.name):
                state.safe_parents(path); files[path] = None
    for path in locations.runtime.rglob('*.pyc'):
        if path.parent.name == '__pycache__':
            state.safe_parents(path); files[path] = None
    return files


def saved_originals(locations, allowed):
    journal = locations.state.with_name('cleanup.json')
    state.safe_parents(journal)
    if journal.is_symlink(): raise RuntimeError(f'Untrusted cleanup record: {journal}')
    if not journal.exists(): return {}
    value = json.loads(journal.read_text())
    result = {}
    for name, snapshot in value.get('metadata', {}).get('originals', {}).items():
        path = Path(name)
        if '..' in path.parts or not (path in allowed or locations.runtime in path.parents):
            raise RuntimeError(f'Unrecognized restored-original recovery path: {path}')
        state.validate(snapshot)
        result[path] = snapshot
    return result


def apply_files(files, locations, extra_roots=(), originals=None):
    journal = locations.state.with_name('cleanup.json')
    state.safe_parents(journal)
    if journal.is_symlink(): raise RuntimeError(f'Untrusted cleanup record: {journal}')
    roots = (locations.home, locations.config, locations.data, locations.state.parent.parent, *extra_roots)
    if locations.session_runtime is not None: roots += (locations.session_runtime,)
    prior = json.loads(journal.read_text()) if journal.exists() else {'files': {}}
    allowed = set(files)
    for name in prior.get('files', {}):
        path = Path(name)
        if '..' in path.parts or not any(path == root or root in path.parents for root in roots):
            raise RuntimeError(f'Unrecognized cleanup recovery path: {name}')
        allowed.add(path)
    with state.Store(journal, allowed) as store:
        preserved = store.state['metadata'].setdefault('originals', {})
        for path, value in (originals or {}).items():
            if value is not None:
                state.validate(value)
                preserved.setdefault(str(path), value)
        replay = {Path(name): record.get('pending', record['installed']) for name, record in store.state['files'].items()}
        replay.update({path: None if data is None else state.file(data, path.stat().st_mode & 0o777 if path.exists() else 0o644)
                       for path, data in files.items()})
        store.state['metadata']['phase'] = 'pending'; store.save()
        store.apply(replay)
        store.state['metadata']['phase'] = 'complete'; store.save()


def finish(locations):
    # Records are only discarded after every cleanup phase has succeeded.
    if locations.desktop_state.exists():
        raise RuntimeError('Desktop ownership remains unresolved; retain recovery records')
    cleanup = locations.state.with_name('cleanup.json')
    if cleanup.exists():
        record = json.loads(cleanup.read_text())
        if record.get('metadata', {}).get('phase') != 'complete' or any('pending' in item for item in record.get('files', {}).values()):
            raise RuntimeError('Cleanup is incomplete; retain recovery records')
    if locations.state.exists():
        record = json.loads(locations.state.read_text())
        if record.get('files') or record.get('metadata', {}).get('phase') not in ('removed', None):
            raise RuntimeError('Unresolved installation ownership remains; retain recovery records')
        locations.state.unlink()
    for name in ('cleanup.json', 'cleanup.lock', 'install.lock', 'desktop-install.lock', 'operation.lock'):
        path = locations.state.with_name(name)
        state.safe_parents(path)
        if path.is_symlink(): raise RuntimeError(f'Untrusted cleanup record: {path}')
        path.unlink(missing_ok=True)
    for directory in (*private_directories(locations), locations.runtime, locations.state.parent):
        if directory.is_symlink(): raise RuntimeError(f'Preserving symlinked directory: {directory}')
        for child in sorted(directory.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if child.is_dir() and not child.is_symlink():
                try: child.rmdir()
                except OSError: pass
        try: directory.rmdir()
        except OSError: pass
    for directory in (locations.config/'gamescope-session-plus/sessions.d', locations.config/'gamescope-session-plus'):
        try: directory.rmdir()
        except OSError: pass
