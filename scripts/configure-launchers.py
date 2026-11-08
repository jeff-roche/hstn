#!/usr/bin/env python3
"""HSTN: create missing launcher shortcuts and apply manifest artwork; close launchers first.

No filters: configure all entries. Repeat --launcher and --target to select subsets.
Preserves existing shortcuts and launch settings. Uses Python standard library only.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/artwork'
MANIFEST = ROOT / 'manifest.json'
STEAM_SLOTS = {'portrait': 'p.png', 'wide': '.png', 'details_background': '_hero.png',
               'icon': '_icon.png', 'logo': '_logo.png'}


def parse_vdf(data):
    """Read Steam's binary shortcut VDF and record string byte ranges."""
    spans = {}

    def parse(pos, path):
        result = {}
        while pos < len(data):
            kind = data[pos]
            pos += 1
            if kind == 8:
                return result, pos
            end = data.index(0, pos)
            key = data[pos:end].decode('utf-8')
            pos = end + 1
            if key in result:
                raise ValueError('Duplicate VDF key')
            if kind == 0:
                start = pos
                value, pos = parse(pos, path + (key,))
                spans[path + (key,)] = (start, pos)
            elif kind == 1:
                end = data.index(0, pos)
                spans[path + (key,)] = (pos, end)
                value = data[pos:end].decode('utf-8')
                pos = end + 1
            elif kind == 2:
                value = struct.unpack_from('<I', data, pos)[0]
                pos += 4
            else:
                raise ValueError(f'Unsupported VDF field type {kind}; file left unchanged')
            result[key] = value
        raise ValueError('Truncated VDF object')

    result, end = parse(0, ())
    if data[end:].strip(b'\x08'):
        raise ValueError('Unexpected trailing VDF data')
    return result, spans


def read_vdf(data):
    return parse_vdf(data)[0]


def steam_running():
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.stat().st_uid == os.getuid() and (proc / 'comm').read_text().strip() == 'steam':
                return True
        except (OSError, ProcessLookupError):
            continue
    return False


def replace_file(path, data, stamp):
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + '.' + stamp + '.bak'))
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        pending = Path(temporary.name)
        temporary.write(data)
    try:
        pending.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def heroic_running():
    # Also catches native Heroic/Electron processes by their executable name.
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if proc.stat().st_uid == os.getuid() and (proc / 'comm').read_text().strip().lower() == 'heroic':
                return True
        except OSError:
            continue
    try:
        result = subprocess.run(['flatpak', 'ps', '--columns=application'],
                                capture_output=True, text=True, check=True)
    except FileNotFoundError:
        return False
    if 'com.heroicgameslauncher.hgl' in result.stdout.splitlines():
        return True
    return False


def load_manifest(path=MANIFEST):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text())
    if manifest['version'] != 1:
        raise ValueError('Unsupported manifest version')
    assets = (path.parent / manifest['assets_dir']).resolve()
    return manifest, assets


def image_bytes(manifest, assets, target, image):
    name = manifest['destinations'][target]['images'][image]
    source = (assets / name).resolve()
    if not source.is_relative_to(assets):
        raise ValueError('Image path escapes assets directory')
    return source.read_bytes()


def select_entries(manifest, launchers=None, targets=None):
    selected = {}
    for launcher in launchers or manifest['launchers']:
        entries = manifest['launchers'][launcher]['entries']
        chosen = {target: entry for target, entry in entries.items()
                  if not targets or target in targets}
        if chosen:
            selected[launcher] = chosen
    if not selected:
        raise ValueError('No manifest entries match the selected launchers and targets')
    if targets:
        missing = set(targets) - {t for entries in selected.values() for t in entries}
        if missing:
            raise ValueError('No selected library has targets: ' + ', '.join(sorted(missing)))
    return selected


def encode_vdf(data):
    """Encode new shortcut records; existing records are never reserialized."""
    result = bytearray()
    for key, value in data.items():
        name = key.encode() + b'\0'
        if isinstance(value, dict):
            result += b'\x00' + name + encode_vdf(value)
        elif isinstance(value, str):
            if '\0' in value:
                raise ValueError('NUL in shortcut string')
            result += b'\x01' + name + value.encode() + b'\0'
        elif isinstance(value, int):
            result += b'\x02' + name + struct.pack('<I', value)
        else:
            raise ValueError('Unsupported shortcut value')
    return bytes(result) + b'\x08'


def switcher_path(executable):
    if Path(executable).name != executable or executable in ('.', '..'):
        raise ValueError('Invalid switcher executable name')
    path = Path.home() / '.local/bin' / executable
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f'Install executable host switcher first: {path}')
    return path


def new_steam_shortcut(title, executable):
    path = switcher_path(executable)
    if '"' in str(path):
        raise ValueError('Steam shortcut path contains a double quote')
    exe = f'"{path}"'
    appid = zlib.crc32((exe + title).encode()) | 0x80000000
    return {
        'appid': appid, 'AppName': title, 'Exe': exe,
        'StartDir': f'"{path.parent}"', 'icon': '', 'ShortcutPath': '',
        'LaunchOptions': '', 'IsHidden': 0, 'AllowDesktopConfig': 1,
        'AllowOverlay': 1, 'OpenVR': 0, 'Devkit': 0, 'DevkitGameID': '',
        'DevkitOverrideAppID': 0, 'LastPlayTime': 0, 'FlatpakAppID': '',
        'sortas': '', 'tags': {},
    }


def prepare_steam(config, manifest, assets, entries):
    config = Path(config).expanduser().resolve()
    if not config.is_dir():
        raise ValueError(f'Steam configuration directory does not exist: {config}')
    shortcuts = config / 'shortcuts.vdf'
    original = shortcuts.read_bytes() if shortcuts.exists() else b'\x00shortcuts\0\x08\x08'
    root, spans = parse_vdf(original)
    files, replacements, additions = {}, [], {}
    for target, entry in entries.items():
        matches = [(key, game) for key, game in root['shortcuts'].items()
                   if Path(game.get('Exe', '').strip('"')).name == entry['executable']]
        if len(matches) > 1:
            raise ValueError(f'Ambiguous duplicate {entry["executable"]} Steam shortcuts')
        if matches:
            key, game = matches[0]
        else:
            game = new_steam_shortcut(manifest['destinations'][target]['title'], entry['executable'])
            if any(g.get('appid') == game['appid'] for g in root['shortcuts'].values()):
                raise ValueError('Steam app ID collision; existing shortcuts left unchanged')
            if any(g.get('AppName') == game['AppName'] for g in root['shortcuts'].values()):
                raise ValueError('Steam title already exists with a different executable')
            key = str(max((int(k) for k in root['shortcuts']), default=-1) + 1)
            root['shortcuts'][key] = game
            additions[key] = game
        appid = game['appid']
        if not isinstance(appid, int) or not appid:
            raise ValueError('Shortcut has no valid Steam app ID')
        grid = config / 'grid'
        for slot, image in entry['slots'].items():
            files[grid / f'{appid}{STEAM_SLOTS[slot]}'] = image_bytes(manifest, assets, target, image)
        changes = {'AppName': manifest['destinations'][target]['title']}
        if 'icon' in entry['slots']:
            changes['icon'] = str(grid / f'{appid}_icon.png')
        for field, value in changes.items():
            if key in additions:
                game[field] = value
            else:
                start, end = spans[('shortcuts', key, field)]
                replacements.append((start, end, value.encode()))
        position = grid / f'{appid}.json'
        if entry.get('logo_position') == 'default' and position.exists():
            metadata = json.loads(position.read_text())
            if 'logoPosition' in metadata:
                del metadata['logoPosition']
                files[position] = (json.dumps(metadata, indent=2) + '\n').encode()
    if additions:
        insertion = spans[('shortcuts',)][1] - 1
        replacements.append((insertion, insertion, encode_vdf(additions)[:-1]))
    updated = original
    for start, end, value in sorted(replacements, reverse=True):
        updated = updated[:start] + value + updated[end:]
    read_vdf(updated)
    files[shortcuts] = updated
    return files


def prepare_heroic(config, manifest, assets, entries):
    config = Path(config).expanduser().resolve()
    if not config.is_dir():
        raise ValueError(f'Heroic configuration directory does not exist: {config}')
    library = config / 'sideload_apps/library.json'
    original = library.read_bytes() if library.exists() else b'{"games": []}'
    data = json.loads(original)
    art = config / 'sideload_apps/artwork'
    files = {}
    for target, entry in entries.items():
        title = manifest['destinations'][target]['title']
        matches = [game for game in data['games']
                   if game.get('runner') == 'sideload' and game.get('title') == title]
        if len(matches) > 1:
            raise ValueError(f'Ambiguous duplicate {title} sideloaded entries')
        if matches:
            game = matches[0]
        else:
            path = switcher_path(entry['executable'])
            used = {g['app_name'] for g in data['games']}
            appid = uuid.uuid4().hex
            while appid in used or (config / 'GamesConfig' / f'{appid}.json').exists():
                appid = uuid.uuid4().hex
            game = {
                'runner': 'sideload', 'app_name': appid, 'title': title,
                'install': {'executable': '/usr/bin/flatpak-spawn', 'platform': 'linux', 'is_dlc': False},
                'folder_name': '/usr/bin', 'is_installed': True, 'canRunOffline': True,
                'browserUrl': '', 'customUserAgent': '', 'launchFullScreen': False,
            }
            settings = {appid: {'launcherArgs': shlex.join([
                '--host', f'--directory={Path.home()}', str(path)])},
                'version': 'v0', 'explicit': True}
            files[config / 'GamesConfig' / f'{appid}.json'] = (json.dumps(settings, indent=2) + '\n').encode()
            data['games'].append(game)
        appid = game['app_name']
        if not isinstance(appid, str) or Path(appid).name != appid or appid in ('.', '..'):
            raise ValueError('Invalid Heroic game ID')
        settings_path = config / 'GamesConfig' / f'{appid}.json'
        settings = json.loads(files[settings_path] if settings_path in files else settings_path.read_bytes())
        args = shlex.split(settings[appid].get('launcherArgs', ''))
        if (game.get('install', {}).get('executable') != '/usr/bin/flatpak-spawn'
                or '--host' not in args or not args or Path(args[-1]).name != entry['executable']):
            raise ValueError(f'{title} does not match the expected host {entry["executable"]} launcher')
        for slot, image in entry['slots'].items():
            if slot not in ('art_cover', 'art_square'):
                raise ValueError(f'Unsupported Heroic slot: {slot}')
            # Stable installed filenames, independent of source draft/version names.
            destination = art / f'{entry["executable"]}-{image}.png'
            files[destination] = image_bytes(manifest, assets, target, image)
            game[slot] = destination.as_uri()
    if json.loads(original) != data:
        files[library] = (json.dumps(data, indent=2) + '\n').encode()
    return files


def apply_files(files):
    stamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
    for path, content in files.items():
        replace_file(path, content, stamp)
    for path, content in files.items():
        if path.read_bytes() != content:
            raise OSError(f'Verification failed: {path}')


def configure_steam(config, manifest_path=MANIFEST, targets=None):
    manifest, assets = load_manifest(manifest_path)
    entries = select_entries(manifest, ['steam'], targets)['steam']
    apply_files(prepare_steam(config, manifest, assets, entries))


def configure_heroic(config, manifest_path=MANIFEST, targets=None):
    manifest, assets = load_manifest(manifest_path)
    entries = select_entries(manifest, ['heroic'], targets)['heroic']
    apply_files(prepare_heroic(config, manifest, assets, entries))


def detect_config(launcher):
    record = Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'hstn/install.json'
    if record.is_file():
        installation = json.loads(record.read_text())
        selected = installation.get('metadata', {}).get('selected_configs', {}).get(launcher)
        if selected:
            path = Path(selected)
            if not path.is_absolute() or not path.is_dir():
                raise ValueError(f'Installed {launcher} configuration is unavailable; specify --{launcher}-config-dir')
            return path
    if launcher == 'steam':
        roots = [Path.home() / '.local/share/Steam', Path.home() / '.steam/steam',
                 Path.home() / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
        candidates = {p.resolve() for root in roots
                      for p in root.glob('userdata/*/config') if p.is_dir()}
    else:
        roots = [Path.home() / '.var/app/com.heroicgameslauncher.hgl/config/heroic',
                 Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'heroic']
        candidates = {p.resolve() for p in roots if p.is_dir() and ((p / 'sideload_apps/library.json').is_file() or (p / 'config.json').is_file())}
    if len(candidates) != 1:
        raise ValueError(f'Cannot select one {launcher} configuration; specify --{launcher}-config-dir')
    return candidates.pop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--launcher', action='append', choices=['steam', 'heroic'], help='Repeatable; default: all')
    parser.add_argument('--target', action='append', choices=['heroic', 'steam', 'desktop'], help='Repeatable; default: all matching destinations')
    parser.add_argument('--steam-config-dir', type=Path, help='Steam userdata/ACCOUNT/config directory')
    parser.add_argument('--heroic-config-dir', type=Path, help='Heroic directory containing sideload_apps')
    args = parser.parse_args(argv)
    try:
        manifest, assets = load_manifest(args.manifest)
        selected = select_entries(manifest, args.launcher, args.target)
        files = {}
        # Preflight every selected library and asset before writing any changes.
        for launcher, entries in selected.items():
            running = steam_running() if launcher == 'steam' else heroic_running()
            if running:
                raise ValueError(f'Close {launcher.capitalize()} completely before configuring it')
            config = getattr(args, f'{launcher}_config_dir') or detect_config(launcher)
            prepare = prepare_steam if launcher == 'steam' else prepare_heroic
            files.update(prepare(config, manifest, assets, entries))
        apply_files(files)
        for launcher, entries in selected.items():
            print(f'Configured {launcher}: {", ".join(entries)}')
    except (OSError, ValueError, KeyError, TypeError, struct.error, subprocess.SubprocessError) as error:
        print(f'Configuration failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
