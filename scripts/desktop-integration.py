#!/usr/bin/env python3
"""Install and control HSTN's KDE Desktop integration (user files only)."""
import argparse
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UNIT = 'hstn-desktop-overlay.service'
BUS = 'org.hstn.DesktopOverlay'
SESSION_ENV_KEYS = ('DISPLAY','XAUTHORITY','WAYLAND_DISPLAY','XDG_CURRENT_DESKTOP',
                    'XDG_SESSION_TYPE','XDG_SESSION_ID','DBUS_SESSION_BUS_ADDRESS','KDE_FULL_SESSION')


def run(arguments, timeout=20, check=True):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'Command failed: {arguments[0]}')
    return result


def exec_arg(value):
    value = str(value)
    if any(c in value for c in '\n\r\x00'):
        raise ValueError('Newlines and NUL are not supported in Desktop command paths')
    escaped = ''.join('\\' + c if c in '\\"`$' else c for c in value)
    return '"' + escaped.replace('\\', '\\\\').replace('%', '%%') + '"'


def unit_arg(value):
    # systemd command parsing and specifier expansion, not shell quoting.
    return json.dumps(str(value), ensure_ascii=False).replace('%', '%%').replace('$', '$$')


def string_value(value):
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r')


def install_files(root, home, data, config, desktop, runtime_root=None):
    root = Path(root).resolve()
    runtime = Path(runtime_root) if runtime_root is not None else root
    helper = runtime/'scripts/desktop-integration.py'
    hstn = runtime/'scripts/hstn'
    files = {}
    manifest = json.loads((root/'manifest.json').read_text())
    for key, title, command, icon in (
        ('steam', 'Switch to Steam', [hstn, 'switch', 'steam'], runtime/manifest['assets_dir']/manifest['destinations']['steam']['images']['icon']),
        ('heroic', 'Switch to Heroic', [hstn, 'switch', 'heroic'], runtime/manifest['assets_dir']/manifest['destinations']['heroic']['images']['icon']),
        ('open', 'Open HSTN', [helper, 'open'], runtime/'assets/logo/hstn-rocket-256.png'),
    ):
        text = '\n'.join(['[Desktop Entry]', 'Type=Application', f'Name={title}',
            'Comment=HSTN — Mission control for Linux gaming sessions',
            'Exec=' + ' '.join(exec_arg(arg) for arg in ['/usr/bin/python3', '-B', *command]),
            'Icon=' + string_value(icon),
            *(['StartupWMClass=hstn-overlay'] if key == 'open' else []),
            'Terminal=false', 'Categories=Game;', 'StartupNotify=false', ''])
        name = f'hstn-{key}.desktop'
        files[Path(data)/'applications'/name] = (text, 0o644)
        files[Path(desktop)/name] = (text, 0o755)
    autostart = '\n'.join(['[Desktop Entry]', 'Type=Application', 'Name=HSTN Desktop overlay',
        'Comment=Enable PS+Create for HSTN during KDE Desktop sessions',
        'Exec=' + ' '.join(exec_arg(arg) for arg in ['/usr/bin/python3', '-B', helper, 'autostart']),
        'OnlyShowIn=KDE;', 'Terminal=false', 'X-KDE-autostart-phase=2', ''])
    files[Path(config)/'autostart/hstn-desktop-overlay.desktop'] = (autostart, 0o644)
    template = (root/'templates/systemd/hstn-desktop-overlay.service').read_text()
    command = unit_arg(runtime/'src/session-overlay.py')
    template = template.replace('"@ROOT@/src/session-overlay.py"', command)
    files[Path(config)/'systemd/user'/UNIT] = (template, 0o644)
    # Install the conflict/ordering change along with the existing Gamescope unit.
    files[Path(config)/'systemd/user/session-switch-overlay.service'] = (
        (root/'templates/systemd/session-switch-overlay.service').read_text(), 0o644)
    return files


def snapshot(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return {'kind':'symlink', 'target':os.readlink(path)}
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f'Refusing to replace non-file: {path}')
    return {'kind':'file', 'data':base64.b64encode(path.read_bytes()).decode(), 'mode':stat.S_IMODE(info.st_mode)}


def atomic_bytes(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_bytes(path, (json.dumps(state, indent=2)+'\n').encode(), 0o600)


def load_state(path):
    if path.exists():
        state = json.loads(path.read_text())
        if state.get('version') != 1:
            raise RuntimeError('Unsupported Desktop installation record')
        return state
    return {'version':1, 'files':{}}


def apply_files(files, state_path):
    state_path = Path(state_path)
    require_focused_ownership(state_path)
    state = load_state(state_path)
    # Detect user edits before changing any files.
    for path in files:
        record = state['files'].get(str(path))
        if record and snapshot(path) not in (record['installed'], record['previous'], record.get('pending')):
            raise RuntimeError(f'Preserving edited file: {path}. Restore it or remove the integration before reinstalling.')
    for path, (content, mode) in files.items():
        data = content.encode()
        installed = {'kind':'file', 'data':base64.b64encode(data).decode(), 'mode':mode}
        key = str(path)
        if key not in state['files']:
            state['files'][key] = {'previous':snapshot(path), 'installed':installed}
        state['files'][key]['pending'] = installed
        # Record recovery data before the replacement, including partial installs.
        save_state(state_path, state)
        if snapshot(path) != installed:
            atomic_bytes(path, data, mode)
        state['files'][key]['installed'] = installed
        state['files'][key].pop('pending',None)
        save_state(state_path, state)


def restore_snapshot(path, original):
    if original is None:
        path.unlink(missing_ok=True)
    elif original['kind'] == 'file':
        atomic_bytes(path, base64.b64decode(original['data']), original['mode'])
    else:
        temporary = path.with_name('.' + path.name + '.hstn-restore')
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(original['target'])
        os.replace(temporary, path)


def remove_files(state_path):
    state_path = Path(state_path)
    require_focused_ownership(state_path)
    state = load_state(state_path)
    conflicts = []
    for key, record in list(state['files'].items()):
        path = Path(key)
        current = snapshot(path)
        if current == record['installed'] or ('pending' in record and current == record['pending']):
            restore_snapshot(path, record['previous'])
        elif current != record['previous']:
            conflicts.append(key)
            continue
        del state['files'][key]
        save_state(state_path, state)
    if not state['files']:
        state_path.unlink(missing_ok=True)
    return conflicts


def require_focused_ownership(state_path):
    general = Path(state_path).with_name('install.json')
    if general != Path(state_path) and general.exists() and json.loads(general.read_text()).get('files'):
        raise RuntimeError('Desktop files are owned by the general installer; use hstn install/setup or hstn uninstall')


def write_session_environment(runtime, environment):
    if 'KDE' not in environment.get('XDG_CURRENT_DESKTOP', '') or not environment.get('DISPLAY'):
        raise RuntimeError('Run Desktop setup/autostart from the current KDE graphical session')
    text = ''.join(name+'='+json.dumps(environment.get(name,''),ensure_ascii=False)+'\n' for name in SESSION_ENV_KEYS)
    path = Path(runtime)/'hstn-desktop-overlay.env'
    atomic_bytes(path, text.encode(), 0o600)
    return path


def desktop_environment(environment=None, proc=Path('/proc')):
    """Resolve graphical variables from the current KDE bus owner, not old shells."""
    reply = run(['busctl','--user','--json=short','call','org.freedesktop.DBus',
                 '/org/freedesktop/DBus','org.freedesktop.DBus',
                 'GetConnectionUnixProcessID','s','org.kde.plasmashell'], timeout=3)
    pid = json.loads(reply.stdout)['data']
    if isinstance(pid, list) and len(pid) == 1:
        pid = pid[0]
    if type(pid) is not int or pid <= 1:
        raise RuntimeError('Could not identify the current KDE Desktop session')
    process = Path(proc)/str(pid)
    if process.stat().st_uid != os.getuid() or (process/'comm').read_text().strip() != 'plasmashell':
        raise RuntimeError('The current KDE Desktop bus owner could not be verified')
    source = dict(entry.split(b'=',1) for entry in (process/'environ').read_bytes().split(b'\0') if b'=' in entry)
    resolved = dict(os.environ if environment is None else environment)
    for key in SESSION_ENV_KEYS:
        resolved[key] = source.get(key.encode(),b'').decode()
    if 'KDE' not in resolved.get('XDG_CURRENT_DESKTOP','') or not resolved.get('DISPLAY'):
        raise RuntimeError('The current KDE Desktop has no usable graphical environment')
    return resolved


def gamescope_active():
    units = [f'gamescope-session-plus@{client}.service' for client in ('steam','ogui-steam','heroic')]
    return run(['systemctl','--user','is-active','--quiet',*units], check=False).returncode == 0


def start_desktop():
    if gamescope_active():
        raise RuntimeError('A Gamescope session is active; refusing Desktop controller takeover')
    environment = desktop_environment()
    write_session_environment(Path(os.environ['XDG_RUNTIME_DIR']), environment)
    run(['systemctl','--user','start',UNIT])


def ipc(method):
    return run(['qdbus-qt6',BUS,'/Overlay',BUS+'.'+method], timeout=5).stdout.strip()


def open_menu():
    try:
        return ipc('Open')
    except RuntimeError:
        # The autostart/setup environment is authoritative; never import a stale
        # terminal environment into the compositor's service on icon activation.
        if gamescope_active():
            raise RuntimeError('A Gamescope session is active; Desktop HSTN cannot be started here') from None
        if 'KDE' not in os.environ.get('XDG_CURRENT_DESKTOP',''):
            raise RuntimeError('Open Desktop HSTN from KDE Desktop Mode') from None
        run(['systemctl','--user','start',UNIT])
        return ipc('Open')


def locations():
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME',home/'.local/share'))
    config = Path(os.environ.get('XDG_CONFIG_HOME',home/'.config'))
    state = Path(os.environ.get('XDG_STATE_HOME',home/'.local/state'))/'hstn/desktop-install.json'
    desktop = Path(run(['xdg-user-dir','DESKTOP'], timeout=3).stdout.strip())
    if not desktop.is_absolute():
        raise RuntimeError('Cannot determine the XDG Desktop directory')
    return home, data, config, state, desktop


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install','remove','open','hide','status','autostart'))
    args = parser.parse_args(argv)
    try:
        if args.action == 'open':
            open_menu()
        elif args.action == 'hide':
            ipc('Hide')
        elif args.action == 'status':
            print(ipc('Status'))
        elif args.action == 'autostart':
            start_desktop()
        else:
            home, data, config, state, desktop = locations()
            if args.action == 'install':
                if 'KDE' not in os.environ.get('XDG_CURRENT_DESKTOP','') or gamescope_active():
                    raise RuntimeError('Install Desktop integration from KDE Desktop Mode')
                files = install_files(ROOT,home,data,config,desktop)
                apply_files(files,state)
                run(['systemctl','--user','daemon-reload'])
                start_desktop()
                print('Desktop icons installed; HSTN starts hidden at KDE login.')
                print(ipc('Status'))
            else:
                # Stop only this feature, never an active Gamescope session/overlay.
                run(['systemctl','--user','stop',UNIT])
                conflicts = remove_files(state)
                run(['systemctl','--user','daemon-reload'])
                runtime = Path(os.environ['XDG_RUNTIME_DIR'])/'hstn-desktop-overlay.env'
                runtime.unlink(missing_ok=True)
                print('Desktop integration removed.' if not conflicts else 'Preserved edited files:\n'+'\n'.join(conflicts))
                if conflicts:
                    return 1
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'HSTN Desktop: {error}',file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
