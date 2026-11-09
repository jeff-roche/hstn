#!/usr/bin/env python3
"""Install/upgrade HSTN or configure a native package for the current user."""
import argparse
import configparser
import ctypes.util
import fcntl
import importlib.util
import io
import json
import os
import platform
import signal
import time
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
APP = 'com.heroicgameslauncher.hgl'
USER_UNITS = ('hstn-desktop-overlay.service', 'session-switch-overlay.service')
LINKS = {
    'hstn': 'scripts/hstn', 'session-switch': 'scripts/session-switch',
    'session-close': 'scripts/session-close.py', 'session-game-activity': 'scripts/game-activity.py',
    'hstn-overlay': 'src/session-overlay.py',
    **{name: 'scripts/' + name for name in (
        'switch-to-steam', 'switch-to-heroic', 'switch-to-desktop', 'heroic-gamescope',
        'gamescope-client-with-overlay', 'steam-session-with-overlay', 'heroic-session-with-overlay',
        'wait-controller-isolation.py', 'input-guard-status.py', 'controller-route-snapshot.py',
        'playstation-output.py', 'supported-controllers.py', 'heroic-window-focus.py', 'session-transition-guard.py',
        'capture-doctor.py', 'collect-controller-routes.py', 'collect-gamescope-windows.py')},
}


def load(name, relative=None):
    path = ROOT/(relative or f"{'installer' if name in ('install-hstn', 'install-system', 'install-state', 'clean-installation', 'remove-launcher-assets') else 'scripts'}/{name}.py")
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = load('install-state')


class Locations:
    def __init__(self, home, env, desktop):
        def base(value):
            path = Path(value)
            if not path.is_absolute() or any(c in str(path) for c in '\n\r\x00'):
                raise RuntimeError(f'Invalid installation base path: {path}')
            return path.resolve()
        self.home = base(home)
        self.data = base(env.get('XDG_DATA_HOME', self.home/'.local/share'))
        self.config = base(env.get('XDG_CONFIG_HOME', self.home/'.config'))
        self.state = base(env.get('XDG_STATE_HOME', self.home/'.local/state'))/'hstn/install.json'
        self.desktop_state = self.state.with_name('desktop-install.json')
        self.runtime = self.data/'hstn'
        self.desktop = base(desktop)
        self.bin = self.home/'.local/bin'
        self.override = base(env.get('FLATPAK_USER_DIR', self.data/'flatpak'))/'overrides'/APP
        self.session_runtime = base(env['XDG_RUNTIME_DIR']) if env.get('XDG_RUNTIME_DIR') else None
        for path in (self.home, self.data, self.config, self.state, self.desktop, self.override):
            state.safe_parents(path)


def native_installation():
    root = Path('/usr/lib/hstn')
    return root if (root/'PACKAGE-MANAGED').is_file() else None


def package_owned_command():
    path = Path('/usr/bin/hstn')
    if not path.exists():
        return False
    for command in (['rpm', '-qf', str(path)], ['dpkg-query', '-S', str(path)]):
        if shutil.which(command[0]) and run(command, check=False).returncode == 0:
            return True
    return False


def user_files(source, locations, package=False):
    source = Path(source)
    native = native_installation()
    if not package and (native or package_owned_command()):
        raise RuntimeError('HSTN is managed by a package manager; use hstn setup and upgrade/remove through that package manager')
    files = {}
    target = source if package else locations.runtime
    if not package:
        builder = load('package', 'installer/package.py')
        for name in builder.inventory(source):
            files[target/name] = state.file((source/name).read_bytes(), builder.file_mode(name))
    files.update({locations.bin/name: {'kind': 'symlink', 'target': str(target/relative)}
                  for name, relative in LINKS.items()})
    for name in ('steam', 'ogui-steam', 'heroic'):
        files[locations.config/'gamescope-session-plus/sessions.d'/name] = state.file(
            (source/'templates/config/gamescope-session-plus/sessions.d'/name).read_bytes())
    desktop = load('desktop-integration')
    # Generate from the destination layout while reading source templates.
    generated = desktop.install_files(source, locations.home, locations.data, locations.config,
                                      locations.desktop, runtime_root=target)
    for path, (content, mode) in generated.items():
        if path.name in USER_UNITS:
            for key, value in (('XDG_DATA_HOME', locations.data), ('XDG_CONFIG_HOME', locations.config),
                               ('XDG_STATE_HOME', locations.state.parent.parent)):
                content += 'Environment=' + json.dumps(key + '=' + str(value)).replace('%', '%%') + '\n'
        files[path] = state.file(content.encode(), mode)
    return files


def allowed_paths(locations, files=()):
    # Runtime inventory can shrink on upgrade. Old paths remain bounded to this
    # private tree; no journal entry can authorize writes to another home path.
    allowed = set(files)
    allowed.update(locations.bin/name for name in LINKS)
    allowed.update(locations.config/'gamescope-session-plus/sessions.d'/name for name in ('steam', 'ogui-steam', 'heroic'))
    allowed.add(locations.override)
    allowed.update(load('desktop-integration').install_files(ROOT, locations.home, locations.data,
                                                           locations.config, locations.desktop))
    if locations.state.exists():
        value = json.loads(locations.state.read_text())
        for name in value.get('files', {}):
            path = Path(name)
            if '..' not in path.parts and locations.runtime in path.parents:
                allowed.add(path)
    return allowed


def desktop_record(locations):
    """Validate old /home alias spelling against canonical Desktop targets."""
    expected = load('desktop-integration').install_files(ROOT, locations.home,
        locations.data, locations.config, locations.desktop)
    state.safe_parents(locations.desktop_state)
    if locations.desktop_state.is_symlink():
        raise RuntimeError('Desktop installation record must not be a symlink')
    raw = json.loads(locations.desktop_state.read_text())
    allowed = {}
    for name in raw.get('files', {}):
        path = Path(name)
        if not path.is_absolute() or '..' in path.parts:
            raise RuntimeError(f'Unrecognized Desktop ownership path: {name}')
        canonical = path.parent.resolve()/path.name
        if canonical not in expected or canonical in allowed.values():
            raise RuntimeError(f'Unrecognized Desktop ownership path: {name}')
        allowed[name] = canonical
    return state.Store(locations.desktop_state, allowed), allowed


def import_desktop(store, locations, files):
    if not locations.desktop_state.exists():
        return
    # Older focused setup remains the authority until the merged journal is
    # durably saved. Repeating an interrupted migration keeps the first backups.
    old, canonical = desktop_record(locations)
    with old as prior:
        for name, record in prior.state['files'].items():
            store.state['files'].setdefault(str(canonical[name]), record)
        store.check(files)
        store.save()
        locations.desktop_state.unlink()


def validate_user_plan(locations, files):
    store = state.Store(locations.state, allowed_paths(locations, files)).read()
    if locations.desktop_state.exists():
        old, canonical = desktop_record(locations)
        old.read()
        for name, record in old.state['files'].items():
            store.state['files'].setdefault(str(canonical[name]), record)
    store.check(files)
    return store


def apply_user(source, locations, files, package=False):
    with state.Store(locations.state, allowed_paths(locations, files)) as store:
        import_desktop(store, locations, files)
        previous_method = store.state['metadata'].get('method')
        method = 'package' if package else 'standalone'
        if previous_method and previous_method != method:
            raise RuntimeError('Remove the previous user installation before changing installation methods')
        store.check(files)
        store.state['metadata'].update({'method': method, 'version': (Path(source)/'VERSION').read_text().strip(),
                                        'desktop': str(locations.desktop), 'phase': 'user-files'})
        store.save()
        store.apply(files)
        # Retired package files are restored before ownership is forgotten.
        retired = set(store.state['files']) - {str(p) for p in files} - {str(locations.override)}
        conflicts = store.remove(retired)
        if conflicts:
            raise RuntimeError('Preserving edited retired files: ' + ', '.join(conflicts))


def remove_user(locations):
    if not locations.state.exists() and not locations.desktop_state.exists():
        return []
    with state.Store(locations.state, allowed_paths(locations)) as store:
        import_desktop(store, locations, {})
        conflicts = store.remove()
        store.state['metadata']['phase'] = 'conflicts' if conflicts else 'removed'
        store.save()
        return conflicts


def run(args, check=True, timeout=30):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'Command failed: {args[0]}')
    return result


def running_launchers():
    config = load('configure-launchers')
    return [name for name, check in (('Steam', config.steam_running), ('Heroic', config.heroic_running))
            if check()]


def desktop_idle(check_launchers=True):
    errors = []
    if 'KDE' not in os.environ.get('XDG_CURRENT_DESKTOP', ''):
        errors.append('Run installation/removal from KDE Desktop Mode')
    desktop = load('desktop-integration')
    if desktop.gamescope_active():
        errors.append('An active Gamescope session prevents installation/removal')
    running = running_launchers() if check_launchers else []
    if running:
        errors.append('Close these running launchers before installation/removal: ' + ', '.join(running))
    result = run([sys.executable, '-B', ROOT/'scripts/game-activity.py', '--check'], check=False)
    if result.returncode:
        errors.append('Games must be closed and the activity check must succeed: ' + (result.stdout or result.stderr).strip())
    return errors


def request_heroic_close(proc=Path('/proc')):
    """Send SIGTERM only to this user's Heroic main processes, through pidfds."""
    for process in Path(proc).glob('[0-9]*'):
        try:
            if process.stat().st_uid != os.getuid() or (process/'comm').read_text().strip().lower() != 'heroic':
                continue
            args = (process/'cmdline').read_bytes().split(b'\0')
            if any(arg == b'--type' or arg.startswith(b'--type=') for arg in args):
                continue  # Electron renderer/GPU children exit with their parent.
            started = (process/'stat').read_text().rsplit(') ', 1)[1].split()[19]
            fd = os.pidfd_open(int(process.name))
            try:
                if (process/'stat').read_text().rsplit(') ', 1)[1].split()[19] != started:
                    continue
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
        except (FileNotFoundError, ProcessLookupError):
            continue


def close_running_launchers(timeout=30):
    errors = desktop_idle(check_launchers=False)
    if errors:
        raise RuntimeError('Cannot close launchers:\n- ' + '\n- '.join(errors))
    running = running_launchers()
    if not running:
        return
    print('Closing running launchers: ' + ', '.join(running))
    for launcher in running:
        # A game may have started since the initial check. Never terminate games.
        errors = desktop_idle(check_launchers=False)
        if errors:
            raise RuntimeError('Cannot close launchers:\n- ' + '\n- '.join(errors))
        if launcher not in running_launchers():
            continue
        try:
            if launcher == 'Steam':
                command = ['steam', '-shutdown'] if shutil.which('steam') else [
                    'flatpak', 'run', 'com.valvesoftware.Steam', '-shutdown']
                result = run(command, check=False, timeout=20)
                if result.returncode:
                    print('Steam shutdown request: ' + (result.stderr or result.stdout).strip())
            else:
                request_heroic_close()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            print(f'Could not request {launcher} shutdown: {error}', file=sys.stderr)
    deadline = time.monotonic() + timeout
    remaining = running_launchers()
    while remaining and time.monotonic() < deadline:
        time.sleep(0.5)
        remaining = running_launchers()
    if remaining:
        raise RuntimeError('Close these launchers manually, then retry: ' + ', '.join(remaining))
    print('Launchers closed. Continuing installation/removal.')


def selected_configs(options):
    config = load('configure-launchers')
    selected = {}
    for name in ('steam', 'heroic'):
        path = options.get(name + '_config_dir')
        path = Path(path) if path else config.detect_config(name)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError(f'{name} configuration must be an existing absolute directory: {path}')
        selected[name] = path
    return selected


def preflight(source, locations, options, configure=False):
    errors = []
    if os.geteuid() == 0:
        errors.append('Run HSTN installation as your normal user; only the separate system phase uses sudo')
    try:
        release = platform.freedesktop_os_release()
        if 'bazzite' not in ' '.join(release.get(k, '') for k in ('ID', 'VARIANT_ID', 'NAME')).lower():
            errors.append('This release supports Bazzite KDE only')
    except OSError as error:
        errors.append(f'Cannot identify supported OS: {error}')
    tools = ('bash', 'python3', 'busctl', 'systemctl', 'systemd-run', 'systemd-inhibit', 'flatpak',
             'flatpak-spawn', 'steamosctl', 'gamescope', 'gamescope-session-plus', 'xprop', 'xwininfo',
             'pgrep', 'notify-send', 'timeout', 'qdbus-qt6', 'xdg-user-dir', 'sudo')
    missing = [name for name in tools if not shutil.which(name)]
    if missing:
        errors.append('Missing required commands: ' + ', '.join(missing))
    for name in ('X11', 'XRes'):
        if not ctypes.util.find_library(name):
            errors.append(f'Missing required library: {name}')
    doctor = load('doctor')
    status, detail = doctor.module_check()
    if status != 'PASS':
        errors.append(detail)
    try:
        load('package', 'installer/package.py').inventory(source)
        load('install-system').check_sddm_precedence()
        if not missing:
            errors.extend(desktop_idle())
            for unit in ('inputplumber.service', 'sddm.service'):
                if run(['systemctl', 'is-active', unit], check=False).stdout.strip() != 'active':
                    errors.append(f'Required service is not active: {unit}')
            for name in ('steam', 'heroic'):
                status, detail = getattr(doctor, name + '_check')()
                if status != 'PASS':
                    errors.append(f'{name}: {detail}')
            status, detail = doctor.manager_check()
            if status != 'PASS':
                errors.append(detail)
            # Reject unsupported effective service overrides before stopping the
            # user's menu or replacing any runtime files. The root phase checks
            # again immediately before changing/starting the guard.
            load('install-system').verify_service_layout(Path('/'), run,
                package=(Path(source)/'PACKAGE-MANAGED').is_file())
            # Both installation scopes at once require selection beyond this
            # initial supported scope; never silently edit another deployment.
            installations = run(['flatpak', 'list', '--app', '--columns=application,installation']).stdout
            if sum(line.split()[0] == APP for line in installations.splitlines() if line.split()) != 1:
                errors.append('Heroic must have exactly one Flatpak deployment; resolve duplicate user/system installations')
            selected_configs(options)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        errors.append(str(error))
    return errors


def permission_file(locations):
    status, detail = load('doctor').permission_check()
    if status == 'PASS':
        return {}
    if status != 'FAIL':
        raise RuntimeError(detail)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    if locations.override.exists():
        parser.read_string(locations.override.read_text())
    if not parser.has_section('Session Bus Policy'):
        parser.add_section('Session Bus Policy')
    parser.set('Session Bus Policy', 'org.freedesktop.Flatpak', 'talk')
    output = io.StringIO()
    parser.write(output, space_around_delimiters=False)
    return {locations.override: state.file(output.getvalue().encode())}


def system_phase(action, package=False):
    errors = desktop_idle()
    if errors:
        raise RuntimeError('; '.join(errors))
    print('HSTN system phase: guard helper/unit, Heroic login entry, SDDM SessionDir, root-private ownership record.', flush=True)
    print('System paths: /usr/local/libexec/session-switch-input-guard.py, /etc/systemd/system/session-switch-input-guard.service, '
          '/etc/wayland-sessions/gamescope-session-heroic.desktop, /etc/sddm.conf.d/zzzzz-hstn-sessions.conf, /var/lib/hstn/', flush=True)
    stage = run(['/usr/bin/sudo', '/usr/bin/mktemp', '-d', '/var/tmp/hstn-install.XXXXXXXX']).stdout.strip()
    if not stage.startswith('/var/tmp/hstn-install.') or Path(stage).parent != Path('/var/tmp'):
        raise RuntimeError('Invalid root staging path')
    try:
        run(['/usr/bin/sudo', '/usr/bin/install', '-d', '-o', 'root', '-g', 'root', '-m', '0700', stage + '/scripts', stage + '/installer', stage + '/templates/systemd'])
        for name in ('installer/install-system.py', 'installer/install-state.py', 'scripts/doctor.py',
                     'scripts/input-guard-status.py', 'scripts/session-switch-input-guard.py',
                     'templates/systemd/session-switch-input-guard.service'):
            run(['/usr/bin/sudo', '/usr/bin/install', '-o', 'root', '-g', 'root', '-m', '0600', ROOT/name, stage + '/' + name])
        result = run(['/usr/bin/sudo', '/usr/bin/python3', '-I', '-B', stage + '/installer/install-system.py', action,
                      *(['--package'] if package else [])], timeout=240)
        if result.stdout:
            print(result.stdout, end='')
    finally:
        run(['/usr/bin/sudo', '/usr/bin/rm', '-rf', '--', stage], check=False)


def update_metadata(locations, **values):
    with state.Store(locations.state, allowed_paths(locations)) as store:
        store.state['metadata'].update(values)
        store.save()


def restore_overlays(previous, runner=None):
    runner = runner or run
    runner(['systemctl', '--user', 'daemon-reload'])
    for unit in USER_UNITS:
        if previous.get(unit) and runner(['systemctl', '--user', 'cat', unit], check=False).returncode == 0:
            runner(['systemctl', '--user', 'start', unit])


def removal_libraries(locations, options, metadata):
    selected = metadata.get('selected_configs', {})
    found = {}
    for launcher in ('steam', 'heroic'):
        explicit = options.get(launcher + '_config_dir')
        if explicit:
            paths = {Path(explicit).resolve()}
        else:
            paths = {Path(selected[launcher]).resolve()} if selected.get(launcher) else set()
            if launcher == 'steam':
                for base in (locations.home/'.local/share/Steam', locations.home/'.steam/steam',
                             locations.home/'.var/app/com.valvesoftware.Steam/.local/share/Steam'):
                    paths.update(p.resolve() for p in base.glob('userdata/*/config') if p.is_dir())
            else:
                paths.update((locations.home/'.var/app/com.heroicgameslauncher.hgl/config/heroic',
                              locations.config/'heroic'))
        found[launcher] = sorted(path for path in paths if path.is_dir())
    return found


def confirm_launcher(launcher):
    prompt = f'Configure {launcher.title()} shortcuts? [y/n]: '
    try:
        # Downloaded installers may use stdin for their script body. Read from
        # the controlling terminal in that case, rather than consuming code.
        if sys.stdin.isatty():
            while True:
                answer = input(prompt).strip().lower()
                if answer in ('y', 'yes', 'n', 'no'):
                    return answer in ('y', 'yes')
                print('Please enter y or n.')
        with open('/dev/tty') as terminal_input, open('/dev/tty', 'w') as terminal:
            while True:
                terminal.write(prompt)
                terminal.flush()
                answer = terminal_input.readline()
                if not answer:
                    return False
                answer = answer.strip().lower()
                if answer in ('y', 'yes', 'n', 'no'):
                    return answer in ('y', 'yes')
                terminal.write('Please enter y or n.\n')
    except (EOFError, OSError):
        print(f'{launcher.title()} configuration skipped: no interactive terminal. '
              'Use -y to configure automatically.')
        return False


def configure_installed_launchers(installed, selected, assume_yes=False):
    failed = False
    for launcher, config in selected.items():
        retry = f'hstn configure --launcher {launcher}'
        if not assume_yes and not confirm_launcher(launcher):
            print(f'{launcher.title()} configuration skipped. Configure later: {retry}')
            continue
        try:
            result = run([sys.executable, '-B', installed/'scripts/configure-launchers.py',
                          '--launcher', launcher, f'--{launcher}-config-dir', config],
                         check=False, timeout=90)
            print(result.stdout, end='')
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or 'Configurator returned an error')
            print(f'{launcher.title()} shortcuts and artwork configured.')
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            print(f'{launcher.title()} configuration failed: {error}. Retry: {retry}', file=sys.stderr)
            failed = True
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='install', choices=('install', 'setup', 'uninstall', 'status'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('-c', '--close-launchers', action='store_true',
                        help='Authorize closing running launchers before installation/removal (no extra prompts)')
    parser.add_argument('--status', action='store_true', help='Read installation state without changing anything')
    parser.add_argument('--user-only', action='store_true', help='Explicitly skip the system phase (reports incomplete prerequisites)')
    parser.add_argument('--clean-slate', action='store_true', help='Uninstall recognized pre-installer HSTN pieces as well (preserves source and unrelated games)')
    parser.add_argument('-y', '--yes', dest='configure_launchers',
                        action='store_true', help='Configure all detected launchers without prompting')
    parser.add_argument('--steam-config-dir', type=Path)
    parser.add_argument('--heroic-config-dir', type=Path)
    args = parser.parse_args(argv)
    operation = None
    recover_activity = None
    try:
        home = Path.home().resolve()
        state_base = Path(os.environ.get('XDG_STATE_HOME', home/'.local/state'))
        if not state_base.is_absolute():
            raise RuntimeError('XDG_STATE_HOME must be absolute')
        state_path = state_base.resolve()/'hstn/install.json'
        # Status is truly read-only: no mkdir, locking, bytecode or service calls.
        if args.action == 'status' or args.status:
            if state_path.exists():
                record = json.loads(state_path.read_text())
                print(json.dumps({'record': str(state_path), 'metadata': record.get('metadata', {}),
                                  'owned_files': len(record.get('files', {}))}, indent=2))
            else:
                print('HSTN is not installed for this user.')
            return 0
        if os.geteuid() == 0:
            raise RuntimeError('Run the installer as your normal user, without sudo')
        if args.clean_slate and args.action != 'uninstall':
            raise RuntimeError('--clean-slate is only valid with uninstall')
        if args.action != 'uninstall' and state_path.with_name('cleanup.json').exists():
            raise RuntimeError('An uninstall cleanup record remains; finish uninstall before installing again')
        has_record = any(state_path.with_name(name).exists() for name in ('install.json', 'desktop-install.json', 'cleanup.json'))
        if args.action == 'uninstall' and not has_record and not args.clean_slate:
            print('No HSTN user installation record. No files or services changed.')
            return 0
        metadata = json.loads(state_path.read_text()).get('metadata', {}) if state_path.exists() else {}
        desktop = metadata.get('desktop') or run(['xdg-user-dir', 'DESKTOP']).stdout.strip()
        locations = Locations(home, os.environ, desktop)
        package = (ROOT/'PACKAGE-MANAGED').is_file()
        if args.action == 'setup' and not package:
            raise RuntimeError('hstn setup is for native packages; use hstn install for standalone installation')
        if args.action == 'install' and package:
            raise RuntimeError('This is a native package; use hstn setup and the package manager for upgrades')
        if args.close_launchers and not args.dry_run:
            close_running_launchers()
        if args.action == 'uninstall':
            errors = desktop_idle()
            plan = {}
            owned = state.Store(locations.state, allowed_paths(locations)).read()
            if locations.desktop_state.exists():
                old, canonical = desktop_record(locations)
                old.read()
                for name, record in old.state['files'].items():
                    owned.state['files'].setdefault(str(canonical[name]), record)
            restore_paths = list(owned.state['files'])
            handled = {Path(key): record.get('pending', record['installed']) for key, record in owned.state['files'].items()}
            originals = {Path(key): record['previous'] for key, record in owned.state['files'].items()}
            cleanup = load('clean-installation')
            removal = load('remove-launcher-assets')
            samples = cleanup.templates(ROOT, LINKS)
            originals = {**cleanup.saved_originals(locations, allowed_paths(locations)), **originals}
            libraries = removal_libraries(locations, vars(args), metadata)
            library_files = {}
            for launcher, paths in libraries.items():
                for path in paths:
                    library_files.update(getattr(removal, launcher + '_files')(path, locations.home))
            extra_roots = [path for paths in libraries.values() for path in paths]
            legacy_files = cleanup.user_files(locations, samples, legacy=args.clean_slate, handled=handled, originals=originals)
            if args.clean_slate:
                if native_installation() or package:
                    raise RuntimeError('Remove native HSTN packages through the package manager before clean-slate cleanup')
                # Public system files can be checked before user mutation; root
                # ownership and recovery records are rechecked by the root stage.
                root_removals = load('install-system').legacy_system_files(ROOT, check_trust=False) if not args.user_only else {}
        else:
            plan = user_files(ROOT, locations, package=package)
            errors = preflight(ROOT, locations, vars(args), configure=args.configure_launchers)
            if not errors:
                plan.update(permission_file(locations))
                validate_user_plan(locations, plan)
        affected = len(restore_paths) + len(library_files) + len(legacy_files) if args.action == 'uninstall' else len(plan)
        print(f'HSTN {args.action}: {affected} user file operations; runtime {ROOT if package else locations.runtime}')
        print(f'Ownership record: {locations.state}')
        print('System phase: ' + ('skipped by --user-only' if args.user_only else 'root-owned guard/session files and service readiness'))
        if errors:
            raise RuntimeError('Preflight failed before installation changes:\n- ' + '\n- '.join(errors))
        if args.dry_run:
            if args.action == 'uninstall':
                for path in restore_paths:
                    print('  restore/remove if still owned: ' + path)
                for path, value in {**library_files, **legacy_files}.items():
                    print(f'  {"remove" if value is None else "update"}: {path}')
                if args.clean_slate:
                    for path in root_removals:
                        print('  system remove: ' + str(path))
            else:
                for path in plan:
                    print(f'  {"replace" if path.exists() or path.is_symlink() else "create"}: {path}')
            print('Dry run: no files or services changed.')
            return 0
        locations.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Lock the stable state base directory: no persistent installer lock
        # artifact needs to survive a successful complete uninstall.
        fd = os.open(locations.state.parent.parent, os.O_RDONLY | os.O_DIRECTORY)
        operation = fd
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another HSTN installation operation is in progress') from None
        # Preserve original overlay activity before any operation, for failed-install recovery.
        active = {unit: run(['systemctl', '--user', 'is-active', unit], check=False).stdout.strip() == 'active'
                  for unit in USER_UNITS}
        if args.action != 'uninstall':
            with state.Store(locations.state, allowed_paths(locations, plan)) as store:
                store.check(plan)
                store.state['metadata'].setdefault('overlay_activity', active)
                recover_activity = store.state['metadata']['overlay_activity']
                store.save()
        else:
            recover_activity = metadata.get('overlay_activity', {})
        for unit in USER_UNITS:
            if active[unit]:
                run(['systemctl', '--user', 'stop', unit])
        if args.action == 'uninstall':
            run(['qdbus-qt6', 'org.kde.KWin', '/Scripting', 'org.kde.kwin.Scripting.unloadScript', 'hstn-desktop-focus'], check=False)
            if not args.user_only:
                system_phase('clean-slate' if args.clean_slate else 'uninstall', package)
            cleanup.apply_files(library_files, locations, extra_roots, originals=originals)
            conflicts = remove_user(locations)
            run(['systemctl', '--user', 'daemon-reload'])
            if conflicts:
                raise RuntimeError('Preserved edited files; keep the recovery record and resolve conflicts:\n' + '\n'.join(conflicts))
            # Inspect restored originals again, so clean-slate never deletes an
            # unrelated collision that ordinary uninstall just restored.
            legacy_files = cleanup.user_files(locations, samples, legacy=args.clean_slate, originals=originals)
            cleanup.apply_files(legacy_files, locations, extra_roots)
            if not args.clean_slate:
                restore_overlays(recover_activity)
            recover_activity = None
            cleanup.finish(locations)
            print('HSTN uninstalled: shortcuts, owned artwork, diagnostics and empty runtime/state directories removed.'
                  + (' Recognized legacy HSTN pieces were removed; source checkout retained.' if args.clean_slate else ' Unrelated pre-existing files were restored.'))
            return 0
        apply_user(ROOT, locations, plan, package)
        if not args.user_only:
            system_phase('install', package)
        status, detail = load('doctor').permission_check()
        if status != 'PASS':
            raise RuntimeError('Heroic effective permission check failed after setup: ' + detail)
        installed = ROOT if package else locations.runtime
        selected = selected_configs(vars(args))
        update_metadata(locations, phase='configured', selected_configs={k: str(v) for k, v in selected.items()})
        run(['systemctl', '--user', 'daemon-reload'])
        run([sys.executable, '-B', installed/'scripts/desktop-integration.py', 'autostart'])
        result = run([sys.executable, '-B', installed/'scripts/doctor.py'], check=False, timeout=90)
        print(result.stdout, end='')
        if result.returncode:
            raise RuntimeError('Installed doctor reports failures. Installation is recorded; correct prerequisites and retry. ' + result.stderr.strip())
        update_metadata(locations, phase='complete')
        recover_activity = None
        print('HSTN installation complete.')
        return configure_installed_launchers(installed, selected, args.configure_launchers)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'HSTN installation: {error}', file=sys.stderr)
        if recover_activity:
            try:
                restore_overlays(recover_activity)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as recovery_error:
                print(f'Could not restore prior overlay activity: {recovery_error}', file=sys.stderr)
        print('No logout or session switch was requested. After a partial install, retry the same command or use hstn uninstall; keep ownership records.', file=sys.stderr)
        return 1
    finally:
        if operation is not None:
            os.close(operation)


if __name__ == '__main__':
    sys.exit(main())
