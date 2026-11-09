#!/usr/bin/env python3
"""Read-only HSTN setup checks. Never installs, repairs, closes apps or switches sessions."""
import argparse
import configparser
import importlib.util
import json
import os
from pathlib import Path
import shutil
import shlex
import stat
import subprocess
import sys

# Helper imports must not create __pycache__ during a read-only diagnosis.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]


def probe(command, timeout=5):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout.strip() or result.stderr.strip())
    except subprocess.TimeoutExpired:
        return 124, f'Command timed out after {timeout}s'
    except OSError as error:
        return 127, str(error)


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def in_gamescope():
    return 'gamescope' in os.environ.get('XDG_CURRENT_DESKTOP', '').lower().split(':')


def file_check(path, executable=False, trusted=False):
    path = Path(path)
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return 'FAIL', f'{path}: not a regular file'
        if trusted and (path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022):
            return 'FAIL', f'{path}: must be a root-owned regular file, not writable by group/others or a symlink'
        if not os.access(path, os.R_OK | (os.X_OK if executable else 0)):
            return 'FAIL', f'{path}: missing read/execute permission'
        return 'PASS', str(path)
    except OSError as error:
        return 'FAIL', f'{path}: {error.strerror or error}'


def session_dirs(root=Path('/')):
    """Read SDDM's vendor snippets, local snippets, then main local config."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    files = [*sorted((root/'usr/lib/sddm/sddm.conf.d').glob('*.conf')),
             *sorted((root/'etc/sddm.conf.d').glob('*.conf')), root/'etc/sddm.conf']
    for path in files:
        if path.exists():
            with path.open() as stream:
                parser.read_file(stream)
    value = parser.get('Wayland', 'SessionDir', fallback='/usr/local/share/wayland-sessions,/usr/share/wayland-sessions')
    return [item.strip() for item in value.split(',') if item.strip()]


def collect():
    checks = []
    def add(name, status, detail):
        checks.append({'name': name, 'status': status, 'detail': detail})
    def check(name, function):
        try:
            status, detail = function()
        except Exception as error:
            status, detail = 'FAIL', f'Could not inspect: {type(error).__name__}: {error}'
        add(name, status, detail)
    def service(unit, user=False):
        code, output = probe(['systemctl', *(['--user'] if user else []), 'is-active', unit])
        if code == 0 and output == 'active':
            return 'PASS', f'{unit}: active'
        return 'FAIL', f'{unit}: {output or "unavailable"}'

    for tool in ('bash', 'python3', 'busctl', 'systemctl', 'systemd-run', 'systemd-inhibit', 'flatpak',
                 'flatpak-spawn', 'steamosctl', 'gamescope', 'gamescope-session-plus',
                 'xprop', 'xwininfo', 'pgrep', 'notify-send', 'timeout', 'qdbus-qt6'):
        path = shutil.which(tool)
        add(f'tool:{tool}', 'PASS' if path else 'FAIL', path or f'{tool} missing from PATH')
    check('python:overlay', lambda: module_check())
    check('service:inputplumber', lambda: service('inputplumber.service'))
    check('service:input-guard', lambda: service('session-switch-input-guard.service'))
    check('guard:identity', lambda: ('PASS', 'Root guard PID and start time match trusted status')
          if load('input-guard-status').permanent_guard_active()
          else ('FAIL', 'Permanent guard status missing, stale or untrusted; inspect the system service journal'))
    check('guard:boot', lambda: enabled_check())
    native = (ROOT/'PACKAGE-MANAGED').is_file()
    check('guard:installed-helper', lambda: file_check(
        '/usr/libexec/session-switch-input-guard.py' if native else '/usr/local/libexec/session-switch-input-guard.py', trusted=True))
    check('guard:installed-unit', lambda: file_check(
        '/usr/lib/systemd/system/session-switch-input-guard.service' if native else '/etc/systemd/system/session-switch-input-guard.service', trusted=True))

    home = Path.home()
    executable = ('hstn', 'session-switch', 'session-close', 'session-game-activity',
                  'hstn-overlay', 'switch-to-steam', 'switch-to-heroic',
                  'switch-to-desktop', 'gamescope-client-with-overlay',
                  'heroic-session-with-overlay', 'steam-session-with-overlay', 'heroic-gamescope')
    for name in executable:
        check(f'wrapper:{name}', lambda name=name: file_check(home/'.local/bin'/name, executable=True))
    for name in ('input-guard-status.py', 'wait-controller-isolation.py', 'controller-route-snapshot.py',
                 'playstation-output.py', 'heroic-window-focus.py', 'session-transition-guard.py'):
        check(f'helper:{name}', lambda name=name: file_check(home/'.local/bin'/name))
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', home/'.config'))
    check('overlay:unit', lambda: file_check(config_home/'systemd/user/session-switch-overlay.service'))
    if in_gamescope():
        check('overlay:state', lambda: service('session-switch-overlay.service', user=True))
    for name in ('heroic', 'steam', 'ogui-steam'):
        installed = config_home/'gamescope-session-plus/sessions.d'/name
        def session_config(path=installed, name=name):
            status, detail = file_check(path)
            if status != 'PASS':
                return status, detail
            expected = ROOT/'templates/config/gamescope-session-plus/sessions.d'/name
            if path.read_bytes() != expected.read_bytes():
                return 'WARN', f'{path}: differs from checkout; inspect overlay wrapper configuration'
            return 'PASS', str(path)
        check(f'session-wrapper:{name}', session_config)
    check('sddm:session-directories', lambda: sddm_check())
    check('session:heroic-entry', lambda: desktop_entry_check('gamescope-session-heroic.desktop', heroic=True))
    check('session:steam-entry', lambda: desktop_entry_check('gamescope-session-ogui-steam.desktop'))
    check('dbus:session-manager', lambda: manager_check())
    check('launcher:steam', lambda: steam_check())
    check('launcher:heroic', lambda: heroic_check())
    check('heroic:host-permission', lambda: permission_check())
    for launcher in ('steam', 'heroic'):
        check(f'library:{launcher}', lambda launcher=launcher: library_check(launcher))
    check('manifest:artwork', lambda: artwork_check())

    if in_gamescope():
        check('controller:isolation', lambda: routing_check())
    return checks


def module_check():
    code, detail = probe([sys.executable, '-B', '-c', 'from PySide6 import QtCore, QtDBus, QtGui, QtWidgets'])
    return ('FAIL', detail) if code else ('PASS', 'PySide6 QtCore/QtDBus/QtGui/QtWidgets import successfully')


def enabled_check():
    code, detail = probe(['systemctl', 'is-enabled', 'session-switch-input-guard.service'])
    return ('PASS', detail) if code == 0 and detail == 'enabled' else ('FAIL', f'Guard not persistently enabled: {detail}')


def sddm_check():
    directories = session_dirs()
    if '/etc/wayland-sessions' not in directories:
        return 'FAIL', 'Effective SDDM Wayland SessionDir excludes /etc/wayland-sessions; Heroic autologin lookup may fail'
    return 'PASS', 'Effective Wayland SessionDir: ' + ', '.join(directories)


def desktop_entry_check(name, heroic=False):
    directories = ['/etc/wayland-sessions'] if heroic else session_dirs()
    for directory in directories:
        path = Path(directory)/name
        if not path.is_file():
            continue
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(path.read_text())
        command = parser.get('Desktop Entry', 'Exec', fallback='')
        args = shlex.split(command)
        target = 'heroic' if heroic else 'ogui-steam'
        valid = len(args) == 2 and args[0] in ('gamescope-session-plus', '/usr/bin/gamescope-session-plus') and args[1] == target
        if not valid or parser.get('Desktop Entry', 'Type', fallback='') != 'Application':
            return 'FAIL', f'{path}: unexpected session Exec or Type'
        return 'PASS', str(path)
    return 'FAIL', f'{name} missing from required session directories'


def manager_check():
    code, detail = probe(['busctl', '--system', '--no-pager', 'introspect',
                          'com.steampowered.SteamOSManager1', '/com/steampowered/SteamOSManager1',
                          'com.steampowered.SteamOSManager1.RootManager'])
    if code or 'SetTemporarySession' not in detail:
        return 'FAIL', 'Cannot find SetTemporarySession on SteamOS Manager system D-Bus'
    return 'PASS', 'SetTemporarySession is present (not called)'


def steam_check():
    native = shutil.which('steam')
    if native:
        return 'PASS', native
    code, detail = probe(['flatpak', 'info', '--show-location', 'com.valvesoftware.Steam'])
    return ('FAIL', 'Neither a steam command nor Steam Flatpak was found') if code else ('PASS', detail)


def heroic_check():
    code, detail = probe(['flatpak', 'info', '--show-location', 'com.heroicgameslauncher.hgl'])
    return ('FAIL', detail) if code else ('PASS', detail)


def permission_check():
    # Flatpak selects the installed deployment and loads its merged context.
    # See flatpak-builtins-info.c: flatpak_context_load_for_deploy(). Do not
    # reconstruct policy from overrides: global/app scope and metadata matter.
    code, detail = probe(['flatpak', 'info', '--show-permissions', 'com.heroicgameslauncher.hgl'])
    if code:
        return 'WARN', f'Could not inspect effective Heroic permissions: {detail}'
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(detail)
    policy = parser.get('Session Bus Policy', 'org.freedesktop.Flatpak', fallback='none')
    if policy in ('talk', 'own'):
        return 'PASS', 'Selected Heroic deployment permits org.freedesktop.Flatpak host calls'
    return 'FAIL', 'Selected Heroic deployment lacks org.freedesktop.Flatpak talk permission; host switch shortcuts need it'


def library_check(launcher):
    config = load('configure-launchers')
    try:
        path = config.detect_config(launcher)
    except (OSError, ValueError) as error:
        return 'FAIL', f'{launcher} configuration: {error}'
    return 'PASS', f'{launcher} configuration found: {path} (not modified)'


def artwork_check():
    config = load('configure-launchers')
    manifest, assets = config.load_manifest()
    missing = [str(assets / image) for destination in manifest['destinations'].values()
               for image in destination['images'].values() if not (assets / image).is_file()]
    return ('FAIL', 'Missing artwork: ' + ', '.join(missing)) if missing else ('PASS', 'Manifest parses and all destination artwork exists')


def input_target():
    target = os.environ.get('SESSION_SWITCH_INPUT_TARGET')
    if target in ('native', 'ds5-single'):
        return target
    # A terminal does not inherit the overlay service's private environment.
    code, state = probe(['systemctl', '--user', 'is-active',
        'gamescope-session-plus@heroic.service', 'gamescope-session-plus@steam.service',
        'gamescope-session-plus@ogui-steam.service', 'hstn-desktop-overlay.service'])
    return 'ds5-single' if code == 0 and 'active' in state.splitlines() else 'native'


def routing_check():
    # Bound the complete scan in a subprocess, including all D-Bus property queries.
    script = """import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('routes',Path(sys.argv[1]))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
r={'routes':m.device_routes(),'inputplumber':m.inputplumber_state()}
print(json.dumps({'issues':m.isolation_issues(r,single_playstation=sys.argv[2]=='ds5-single'),
 'gaps':r['routes']['holder_inspection_errors']}))
"""
    code, detail = probe([sys.executable, '-B', '-c', script,
                          str(ROOT/'scripts/controller-route-snapshot.py'),
                          input_target()], timeout=20)
    if code:
        return 'WARN', 'Controller inspection unavailable: ' + detail
    report = json.loads(detail)
    if report['issues']:
        return 'FAIL', '; '.join(report['issues'])
    if report['gaps']:
        return 'WARN', 'Route prerequisites pass, but some process holders could not be inspected; this is not a live input test'
    return 'PASS', 'Route prerequisites pass; this snapshot does not prove live event isolation'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Print a complete structured report')
    parser.add_argument('-v', '--verbose', action='store_true', help='Show all checks, including passes')
    args = parser.parse_args(argv)
    checks = collect()
    summary = {status: sum(c['status'] == status for c in checks) for status in ('PASS', 'WARN', 'FAIL', 'SKIP')}
    report = {'version': 1, 'tool': 'hstn doctor', 'context': 'gamescope' if in_gamescope() else 'desktop',
              'ok': summary['FAIL'] == 0, 'summary': summary, 'checks': checks}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f'HSTN doctor — {report["context"]} (read-only)')
        for item in checks:
            if args.verbose or item['status'] in ('WARN', 'FAIL'):
                print(f'[{item["status"]}] {item["name"]}: {item["detail"]}')
        print('\n' + ' · '.join(f'{count} {status.lower()}' for status, count in summary.items() if status != 'SKIP' or count))
        print('No changes made.')
    return int(not report['ok'])


if __name__ == '__main__':
    raise SystemExit(main())
