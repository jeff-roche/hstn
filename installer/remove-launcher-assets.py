#!/usr/bin/env python3
"""Plan precise removal of HSTN shortcuts and their unshared launcher assets."""
import importlib.util
import json
from pathlib import Path
import re
import shlex
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'switch-to-steam', 'switch-to-heroic', 'switch-to-desktop',
         'session-switch-test-game', 'controller-input-test'}


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/('installer' if name in ('install-hstn', 'install-system', 'install-state', 'clean-installation', 'remove-launcher-assets') else 'scripts')/f'{name}.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


configurator = load('configure-launchers')
state = load('install-state')


def owned_executable(value, home):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    path = Path(value)
    return (path.is_absolute() and path.name in NAMES
            and path.parent.resolve() == (Path(home)/'.local/bin').resolve())


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for entry in value.values():
            yield from strings(entry)
    elif isinstance(value, list):
        for entry in value:
            yield from strings(entry)


def referenced(path, entries):
    expected = str(path)
    for text in strings(entries):
        if text == expected or text == path.as_uri():
            return True
    return False


def steam_files(config, home):
    config = Path(config)
    library = config/'shortcuts.vdf'
    if not library.exists():
        return {}
    state.safe_parents(library)
    original = library.read_bytes()
    data, spans = configurator.parse_vdf(original)
    entries = data['shortcuts']
    selected = {key: game for key, game in entries.items() if owned_executable(game.get('Exe', ''), home)}
    if not selected:
        return {}
    remaining = {key: game for key, game in entries.items() if key not in selected}
    removals = {}
    ranges = []
    for key, game in selected.items():
        appid = game.get('appid')
        if type(appid) is not int or not appid or sum(g.get('appid') == appid for g in entries.values()) != 1:
            raise ValueError('Steam app ID collision; preserve libraries until it is resolved')
        start, end = spans[('shortcuts', key)]
        ranges.append((start - len(key.encode()) - 2, end))
        grid = config/'grid'
        for path in grid.glob(str(appid) + '*'):
            if re.fullmatch(str(appid) + r'(?:p|_hero|_icon|_logo)?\.(?:png|jpg|jpeg|webp|json)', path.name, re.I):
                state.safe_parents(path)
                if not referenced(path, remaining):
                    removals[path] = None
    updated = original
    for start, end in sorted(ranges, reverse=True):
        updated = updated[:start] + updated[end:]
    configurator.read_vdf(updated)
    return {library: updated, **removals}


def heroic_files(config, home):
    config = Path(config)
    library = config/'sideload_apps/library.json'
    if not library.exists():
        return {}
    state.safe_parents(library)
    data = json.loads(library.read_text())
    selected = []
    for game in data['games']:
        if game.get('runner') != 'sideload':
            continue
        executable = game.get('install', {}).get('executable', '')
        if executable != '/usr/bin/flatpak-spawn' and not owned_executable(executable, home):
            continue
        appid = game.get('app_name')
        if not isinstance(appid, str) or Path(appid).name != appid or appid in ('.', '..'):
            raise ValueError('Invalid Heroic sideload ID')
        settings = config/'GamesConfig'/f'{appid}.json'
        if not settings.exists():
            if owned_executable(executable, home): selected.append(game)
            continue
        state.safe_parents(settings)
        launch = json.loads(settings.read_text()).get(appid, {})
        args = shlex.split(launch.get('launcherArgs', ''))
        if owned_executable(executable, home) or (executable == '/usr/bin/flatpak-spawn'
                and '--host' in args and args and owned_executable(shlex.quote(args[-1]), home)):
            selected.append(game)
    if not selected:
        return {}
    remaining = [game for game in data['games'] if game not in selected]
    removed = {}
    for game in selected:
        appid = game['app_name']
        if sum(g.get('app_name') == appid for g in data['games']) != 1:
            raise ValueError('Duplicate Heroic ID; preserve libraries until it is resolved')
        removed[config/'GamesConfig'/f'{appid}.json'] = None
        for key in ('art_cover', 'art_square', 'art_logo', 'art_background'):
            value = game.get(key, '')
            parsed = urlsplit(value)
            if parsed.scheme == 'file' and not parsed.netloc:
                path = Path(unquote(parsed.path))
                if path.parent == config/'sideload_apps/artwork' and re.fullmatch(
                        r'(?:switch-to-(?:steam|heroic|desktop)|session-switch-test-game|controller-input-test)[\w.-]*\.(?:png|jpg|jpeg|webp)', path.name):
                    state.safe_parents(path)
                    if not referenced(path, remaining):
                        removed[path] = None
    data['games'] = remaining
    return {library: (json.dumps(data, indent=2) + '\n').encode(), **removed}


def apply(files):
    for path, data in files.items():
        if data is None:
            state.restore(path, None)
        else:
            state.atomic(path, data, path.stat().st_mode & 0o777 if path.exists() else 0o644)
