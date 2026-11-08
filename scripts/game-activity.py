#!/usr/bin/env python3
"""HSTN: inspect launcher-tagged processes, or refuse a switch with --check.

Best-effort detection: metadata can be cleared, helpers may linger, and game
launches can race with a scan. Inspection gaps warn but do not block switching.
"""
import importlib.util
import argparse
import json
import os
from pathlib import Path
import shlex
import sys


def switcher_ids():
    """Read actual library IDs instead of hard-coding machine-specific IDs."""
    spec = importlib.util.spec_from_file_location('launcher_config', Path(__file__).resolve().with_name('configure-launchers.py'))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    manifest, _ = config.load_manifest()
    steam, heroic, errors = set(), set(), []
    try:
        root = config.detect_config('steam')
        games = config.read_vdf((root / 'shortcuts.vdf').read_bytes())['shortcuts']
        names = {entry['executable'] for entry in manifest['launchers']['steam']['entries'].values()}
        for game in games.values():
            if Path(game.get('Exe', '').strip('"')).name in names:
                steam.add(str(game['appid']))
    except (OSError, ValueError, KeyError) as error:
        errors.append(f'Steam switcher IDs unavailable: {error}')
    try:
        root = config.detect_config('heroic')
        games = json.loads((root / 'sideload_apps/library.json').read_text())['games']
        names = {entry['executable'] for entry in manifest['launchers']['heroic']['entries'].values()}
        for game in games:
            if game.get('runner') != 'sideload':
                continue
            appid = game['app_name']
            settings = json.loads((root / 'GamesConfig' / f'{appid}.json').read_text())
            args = shlex.split(settings[appid].get('launcherArgs', ''))
            if (game.get('install', {}).get('executable') == '/usr/bin/flatpak-spawn'
                    and '--host' in args and args and Path(args[-1]).name in names):
                heroic.add(appid)
    except (OSError, ValueError, KeyError) as error:
        errors.append(f'Heroic switcher IDs unavailable: {error}')
    return steam, heroic, errors


def scan(proc=Path('/proc'), steam_switchers=None, heroic_switchers=None):
    """Group same-user live processes by launch metadata; never stop anything."""
    steam_switchers = steam_switchers or set()
    heroic_switchers = heroic_switchers or set()
    groups, errors = {}, []
    for process in sorted(proc.glob('[0-9]*'), key=lambda p: int(p.name)):
        try:
            if process.stat().st_uid != os.getuid():
                continue
            env = dict(item.split(b'=', 1) for item in (process / 'environ').read_bytes().split(b'\0') if b'=' in item)
            heroic_id = env.get(b'HEROIC_APP_NAME', b'').decode(errors='replace')
            steam_id = env.get(b'SteamAppId', b'').decode(errors='replace')
            if heroic_id:
                launcher, appid, switchers = 'heroic', heroic_id, heroic_switchers
            elif steam_id.isdecimal() and int(steam_id) > 0:
                launcher, appid, switchers = 'steam', str(int(steam_id)), steam_switchers
            else:
                continue
            key = (launcher, appid)
            group = groups.setdefault(key, {'launcher': launcher, 'app_id': appid,
                                           'switcher': appid in switchers, 'pids': []})
            group['pids'].append(int(process.name))
        except (FileNotFoundError, ProcessLookupError):
            # Normal process exit while enumerating /proc.
            continue
        except OSError as error:
            errors.append(f'Cannot inspect PID {process.name}: {error.strerror}')
    return {'mode': 'diagnostic-only', 'candidates': list(groups.values()), 'errors': errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='Exit 20 for detected games, 0 otherwise; inspection gaps warn')
    args = parser.parse_args(argv)
    try:
        steam, heroic, errors = switcher_ids()
        report = scan(steam_switchers=steam, heroic_switchers=heroic)
        report['errors'] = errors + report['errors']
    except Exception as error:
        print(f'Game activity check failed: {error}', file=sys.stderr)
        return 21
    if not args.check:
        print(json.dumps(report, indent=2))
        return 1 if report['errors'] else 0
    if report['errors']:
        print(f'Warning: game inspection incomplete ({len(report["errors"])} issue(s)).', file=sys.stderr)
        for error in report['errors']:
            print(f'  {error}', file=sys.stderr)
    games = [game for game in report['candidates'] if not game['switcher']]
    if games:
        print('Close running games before switching sessions:', file=sys.stderr)
        for game in games:
            print(f'  {game["launcher"]}: {game["app_id"]}', file=sys.stderr)
        return 20
    return 0


if __name__ == '__main__':
    sys.exit(main())
