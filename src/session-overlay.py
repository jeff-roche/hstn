#!/usr/bin/env python3
"""HSTN controller overlay with guarded Gamescope session switching.

--demo creates a keyboard-input counter behind the overlay.
--manage-input temporarily enables InputPlumber management (restored on exit).
Hold Guide/PS, then press Create/Select to open; PS alone passes to launcher; D-pad selects; Cross/South selects; East closes. Esc closes.
"""
import argparse
import html
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import importlib.util

SERVICE = 'org.shadowblip.InputPlumber'
MANAGER = '/org/shadowblip/InputPlumber/Manager'
COMPOSITE = 'org.shadowblip.Input.CompositeDevice'

_spec = importlib.util.spec_from_file_location('supported_controllers',
    Path(__file__).resolve().parents[1] / 'scripts/supported-controllers.py')
controllers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(controllers)


def bus(*args):
    result = subprocess.run(['busctl', '--system', '--json=short', *args],
                            capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)['data'] if result.stdout.strip() else None


def get_property(path, interface, name):
    return bus('get-property', SERVICE, path, interface, name)


def set_property(path, interface, name, signature, value):
    bus('set-property', SERVICE, path, interface, name, signature, str(value))


def composites():
    result = subprocess.run(['busctl', '--system', '--list', 'tree', SERVICE],
                            capture_output=True, text=True, check=True, timeout=3)
    return [p for p in result.stdout.splitlines() if p.rsplit('/', 1)[-1].startswith('CompositeDevice')]


def compatibility_targets(name, sources, enabled):
    if enabled and 'DualSense' in name and any(path.startswith('/dev/hidraw') for path in sources):
        return ['xb360', 'mouse', 'keyboard']
    return None


def configure_menu_activation(path, restore_default=False):
    # Use InputPlumber's per-composite chord handling. A partial Guide chord
    # is replayed to the launcher on release; a complete chord is consumed.
    keys = ['Gamepad:Button:Guide']
    if not restore_default:
        keys.append('Gamepad:Button:Select')
    target = 'Gamepad:Button:Guide' if restore_default else 'Gamepad:Button:QuickAccess'
    bus('call', SERVICE, path, COMPOSITE, 'SetInterceptActivation', 'ass',
        str(len(keys)), *keys, target)


def desktop_isolation_issues():
    """Desktop Steam can already hold physical FDs before management starts."""
    helper = Path(__file__).resolve().parents[1] / 'scripts/controller-route-snapshot.py'
    try:
        arguments = [sys.executable, '-B', str(helper), '--check-isolation']
        if os.environ.get('SESSION_SWITCH_INPUT_TARGET') == 'ds5-single':
            arguments.append('--single-playstation')
        result = subprocess.run(arguments,
                                capture_output=True, text=True, timeout=3)
        report = json.loads(result.stdout)
        issues = report['isolation_issues']
        if result.returncode and not issues:
            return ['Controller route inspection failed']
        return issues
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
        return ['Could not verify Desktop input isolation: ' + str(error)]


def restore(state):
    # Disable automatic management first, so stopping temporary composites does
    # not create replacements. Existing composites and original modes survive.
    if state.get('manage_changed'):
        try:
            set_property(MANAGER, 'org.shadowblip.InputManager', 'ManageAllDevices', 'b', 'false')
            for path in composites():
                if path not in state.get('baseline', []):
                    bus('call', SERVICE, path, COMPOSITE, 'Stop')
        except Exception as error:
            print(f'Manager restore: {error}', file=sys.stderr)
    for path, mode in state.get('modes', {}).items():
        if state.get('manage_changed') and path not in state.get('baseline', []):
            continue
        try:
            if path in state.get('activation_paths', []):
                configure_menu_activation(path, restore_default=True)
            set_property(path, COMPOSITE, 'InterceptMode', 'u', mode)
        except Exception as error:
            print(f'Input restore: {error}', file=sys.stderr)


# Independent cleanup process: EOF also occurs if the UI crashes/is SIGKILLed.
if '--restore-watchdog' in sys.argv:
    state = {}
    try:
        for line in sys.stdin:
            state = json.loads(line)
    finally:
        restore(state)
    sys.exit(0)

os.environ['QT_QPA_PLATFORM'] = 'xcb'
from PySide6 import QtCore, QtDBus, QtGui, QtWidgets


def xproperty(window, name, value):
    subprocess.run(['xprop', '-id', str(window), '-f', name, '32c', '-set', name, str(value)],
                   check=True, capture_output=True, timeout=2)


def switch_command(helper, target, arguments=None):
    if target not in ('steam', 'heroic', 'desktop'):
        raise ValueError('Unknown session target')
    # Separate cgroup: stopping the Gamescope session also stops this overlay,
    # but must not kill the transition command before its stop job is queued.
    environment = {name: os.environ.get(name, '') for name in (
        'DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE', 'XDG_SESSION_ID')}
    environment['XDG_CURRENT_DESKTOP'] = (
        os.environ.get('XDG_CURRENT_DESKTOP', 'KDE') if os.environ.get('SESSION_SWITCH_DESKTOP_MODE') == '1'
        else 'gamescope')
    return ['--user', '--wait', '--pipe', '--collect', '--quiet',
            '--service-type=exec', '--unit=session-switch-request-' + uuid.uuid4().hex,
            *['--setenv=' + name + '=' + value for name, value in environment.items()],
            '--', str(helper), *(arguments if arguments is not None else [target])]


class SwitchRequest(QtCore.QObject):
    completed = QtCore.Signal(int, str)

    def __init__(self, parent=None, runner='/usr/bin/systemd-run', helper=None, output_limit=16384):
        super().__init__(parent)
        self.runner = runner
        self.output_limit = output_limit
        self.helper = helper or Path.home() / '.local/bin/session-switch'
        self.process = None
        self.output = bytearray()

    @property
    def busy(self):
        return self.process is not None

    def start(self, target, arguments=None):
        if self.busy:
            return False
        args = switch_command(self.helper, target, arguments)
        self.output.clear()
        process = self.process = QtCore.QProcess(self)
        process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self.read_output)
        process.finished.connect(self.finished)
        process.errorOccurred.connect(self.failed)
        process.start(self.runner, args)
        process.closeWriteChannel()
        return True

    def read_output(self):
        if self.process:
            self.output.extend(bytes(self.process.readAllStandardOutput()))
            del self.output[:-self.output_limit]

    def failed(self, error):
        if error == QtCore.QProcess.FailedToStart and self.process:
            message = self.process.errorString()
            self.process.deleteLater()
            self.process = None
            self.completed.emit(127, 'Could not start session switch: ' + message)

    def finished(self, code, status):
        if not self.process:
            return
        self.read_output()
        message = self.output.decode(errors='replace').strip()
        self.process.deleteLater()
        self.process = None
        if status == QtCore.QProcess.CrashExit:
            code = code or 1
        self.completed.emit(code, message)


class ControllerEvents(QtCore.QObject):
    def __init__(self, router, target):
        super().__init__(router)
        self.router, self.target = router, target

    @QtCore.Slot(str, float)
    def on_event(self, event, value):
        self.router.controller_event(self.target, event, value)


class InputRouter(QtCore.QObject):
    action = QtCore.Signal(str)
    input_family = QtCore.Signal(str)
    fatal = QtCore.Signal(str)

    def __init__(self, manage=False, lease=None):
        super().__init__()
        self.state = {'modes': {}, 'manage_changed': False, 'baseline': [], 'activation_paths': []}
        self.watchdog = None
        self.targets = set()
        self.bindings = {}
        self.target_paths = {}
        self.target_families = {}
        self.path_sources = {}
        self.controller_pressed = {}
        self.dbus = QtDBus.QDBusConnection.systemBus()
        self.visible = False
        self.manage = manage
        self.lease = lease
        self.desktop = os.environ.get('SESSION_SWITCH_DESKTOP_MODE') == '1'
        self.pressed = set()
        self.playstation = None
        self.playstation_phase = None
        self.guard_required = os.environ.get('SESSION_SWITCH_REQUIRE_INPUT_GUARD') == '1'
        self.guard_failed = False
        self.guard_status = None
        if self.guard_required:
            spec = importlib.util.spec_from_file_location('overlay_guard_status',
                Path(__file__).resolve().parents[1] / 'scripts/input-guard-status.py')
            self.guard_status = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.guard_status)
        if os.environ.get('SESSION_SWITCH_INPUT_TARGET') == 'ds5-single':
            spec = importlib.util.spec_from_file_location('controller_outputs',
                Path(__file__).resolve().parents[1] / 'scripts/controller-outputs.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.playstation = module.ControllerOutputs(self.set_targets)

    def save(self):
        self.watchdog.stdin.write(json.dumps(self.state) + '\n')
        self.watchdog.stdin.flush()

    def guard_available(self):
        return not self.guard_required or self.guard_status.permanent_guard_active() or self.guard_status.legacy_guard_active()

    def guard_lost(self):
        if not self.guard_failed:
            self.guard_failed = True
            self.fatal.emit('Input guard stopped; disabling the custom overlay.')

    def start(self):
        if not self.guard_available():
            raise RuntimeError('Input guard unavailable; controller ownership was not changed.')
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        self.refresh()

    def start_controller(self):
        issues = controllers.activation_issues()
        if issues:
            raise RuntimeError('; '.join(issues))
        # Do not compete with OpenGamepadUI for ownership of intercepted events.
        if subprocess.run(['pgrep', '-x', 'opengamepadui'], stdout=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('OpenGamepadUI is running; HSTN will not take over its controller input.')
        self.watchdog = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--restore-watchdog'],
                                         stdin=subprocess.PIPE, text=True,
                                         pass_fds=(self.lease.fileno(),) if self.lease else ())
        self.state['baseline'] = composites()
        self.save()
        if self.desktop and self.state['baseline']:
            raise RuntimeError('Existing InputPlumber controller ownership was preserved. Stop its owner before restarting Desktop HSTN.')
        old = get_property(MANAGER, 'org.shadowblip.InputManager', 'ManageAllDevices')
        if self.manage and not old:
            self.state['manage_changed'] = True
            self.save()  # Record restoration intent before mutation.
            set_property(MANAGER, 'org.shadowblip.InputManager', 'ManageAllDevices', 'b', 'true')

    def release_controller(self):
        for target in list(self.targets):
            self.detach_target(target)
        self.controller_pressed.clear()
        self.path_sources.clear()
        self.pressed.clear()
        if self.watchdog:
            self.watchdog.stdin.close()
            self.watchdog.wait(timeout=10)
            self.watchdog = None
        self.state = {'modes': {}, 'manage_changed': False, 'baseline': [], 'activation_paths': []}
        if self.playstation:
            self.playstation = type(self.playstation)(self.set_targets)
            self.playstation_phase = None

    def detach_target(self, target):
        receiver = self.bindings.pop(target, self)
        self.dbus.disconnect(SERVICE, target, 'org.shadowblip.Input.DBusDevice',
                             'InputEvent', receiver, QtCore.SLOT('on_event(QString,double)'))
        self.targets.discard(target)
        self.target_paths.pop(target, None)
        self.target_families.pop(target, None)
        self.controller_pressed.pop(target, None)
        if receiver is not self:
            receiver.deleteLater()

    def set_targets(self, path, targets):
        bus('call', SERVICE, path, COMPOSITE, 'SetTargetDevices', 'as', str(len(targets)), *targets)

    def retire_disconnected(self, current_sources):
        # InputPlumber can retain a composite and its outputs after its last
        # source disappears. Only stop composites HSTN previously intercepted.
        for path in list(current_sources):
            if (not current_sources[path] and path in self.state['modes']
                    and path not in self.state['baseline']):
                bus('call', SERVICE, path, COMPOSITE, 'Stop')
                del current_sources[path]
        return current_sources

    def refresh(self):
        if not self.guard_available():
            self.guard_lost()
            return
        try:
            if not controllers.connected():
                if self.watchdog:
                    self.release_controller()
                    print('Supported controller disconnected; waiting for reconnection.', flush=True)
                return
            if not self.watchdog:
                try:
                    self.start_controller()
                except Exception:
                    self.release_controller()
                    raise
            result = subprocess.run(['busctl', '--system', '--list', 'tree', SERVICE],
                                    capture_output=True, text=True, check=True, timeout=3)
            paths = [p for p in result.stdout.splitlines() if p.rsplit('/', 1)[-1].startswith('CompositeDevice')]
            current_sources = {path: tuple(get_property(path, COMPOSITE, 'SourceDevicePaths')) for path in paths}
            current_sources = self.retire_disconnected(current_sources)
            paths = list(current_sources)
            vanished = {path for path in self.state['modes'] if path not in current_sources or
                        (path in self.path_sources and self.path_sources[path] != current_sources[path])}
            for target, path in list(self.target_paths.items()):
                if path not in paths or path in vanished:
                    self.detach_target(target)
            if vanished:
                for path in vanished:
                    self.state['modes'].pop(path, None)
                self.state['activation_paths'] = [path for path in self.state['activation_paths'] if path not in vanished]
                self.save()
            self.path_sources = current_sources
            if self.playstation and self.state['manage_changed']:
                records = []
                for path in paths:
                    mode = get_property(path, COMPOSITE, 'InterceptMode')
                    records.append({'path': path,
                        'sources': current_sources[path],
                        'targets': get_property(path, COMPOSITE, 'TargetDevices'),
                        'owned': path not in self.state['baseline'] and
                                 (mode == 0 or path in self.state['modes'])})
                candidates = {}
                for record in records:
                    if record['path'] not in self.state['modes'] and controllers.supported_sources(record['sources']):
                        for source in record['sources']:
                            candidates.setdefault(controllers.supported_parent(source), []).append(source)
                blocked = {parent for parent, sources in candidates.items() if controllers.activation_issues(sources)}
                records = [record for record in records if not any(
                    controllers.supported_parent(source) in blocked for source in record['sources'])]
                ready = self.playstation.update(records)
                if self.playstation.phase != self.playstation_phase:
                    self.playstation_phase = self.playstation.phase
                    print(f'Controller output initialization: {self.playstation_phase}', flush=True)
                    for error in self.playstation.failures.values():
                        print(f'Controller initialization: {error}', file=sys.stderr, flush=True)
            for path in paths:
                if self.playstation and self.state['manage_changed'] and path not in self.playstation.ready_paths:
                    continue
                if not controllers.supported_sources(current_sources[path]):
                    continue
                if path in self.state['modes']:
                    continue
                if path in self.state['baseline']:
                    # No getter for prior activation chord: preserve existing owners.
                    continue
                original = get_property(path, COMPOSITE, 'InterceptMode')
                if original != 0:
                    print(f'Controller already intercepted; leaving untouched: {path}', flush=True)
                    continue
                if self.playstation and path in self.playstation.companions:
                    # Keep physical siblings hidden, but never present phantom
                    # gamepads or duplicate their events into our menu.
                    self.state['modes'][path] = original
                    self.save()
                    set_property(path, COMPOSITE, 'InterceptMode', 'u', 2 if self.visible else 1)
                    continue
                replacements = compatibility_targets(
                    get_property(path, COMPOSITE, 'Name'),
                    get_property(path, COMPOSITE, 'SourceDevicePaths'),
                    self.state['manage_changed'] and os.environ.get('SESSION_SWITCH_INPUT_TARGET') == 'xb360')
                if replacements:
                    bus('call', SERVICE, path, COMPOSITE, 'SetTargetDevices',
                        'as', str(len(replacements)), *replacements)
                    print(f'Heroic compatibility output: {path} -> {replacements}', flush=True)
                targets = get_property(path, COMPOSITE, 'DbusDevices')
                if not targets:
                    print(f'Controller has no DBus target: {path}', flush=True)
                    continue
                for target, owner in list(self.target_paths.items()):
                    if owner == path and target not in targets:
                        self.detach_target(target)
                for target in targets:
                    if target not in self.targets:
                        receiver = ControllerEvents(self, target)
                        connected = self.dbus.connect(SERVICE, target, 'org.shadowblip.Input.DBusDevice',
                                                      'InputEvent', receiver, QtCore.SLOT('on_event(QString,double)'))
                        if not connected:
                            raise RuntimeError(f'Cannot subscribe to controller: {target}')
                        self.targets.add(target)
                        self.bindings[target] = receiver
                        self.target_paths[target] = path
                        self.target_families[target] = ('xbox' if any(
                            controllers.xbox_source(source) for source in current_sources[path]) else 'playstation')
                self.state['modes'][path] = original
                self.state['activation_paths'].append(path)
                self.save()
                configure_menu_activation(path)
                set_property(path, COMPOSITE, 'InterceptMode', 'u', 2 if self.visible else 1)
                print(f'Controller ready: {path}', flush=True)
        except Exception as error:
            print(f'Controller discovery: {error}', file=sys.stderr, flush=True)
            if self.playstation and self.playstation.phase == 'failed':
                if hasattr(self, 'timer'):
                    self.timer.stop()
                self.fatal.emit(str(error))

    def capture(self, visible):
        if visible and not self.guard_available():
            self.guard_lost()
            raise RuntimeError('Input guard unavailable')
        if visible and self.desktop:
            if not self.state['modes']:
                raise RuntimeError('No controller is ready. Connect a supported controller and wait for Guide+Select to become available.')
            issues = desktop_isolation_issues()
            if issues:
                raise RuntimeError('; '.join(issues))
        self.visible = visible
        failures = []
        for path in self.state['modes']:
            try:
                set_property(path, COMPOSITE, 'InterceptMode', 'u', 2 if visible else 1)
            except RuntimeError as error:
                if visible:
                    raise
                failures.append(f'{path}: {error}')
        if failures:
            print('Input release: ' + '; '.join(failures), file=sys.stderr, flush=True)

    @QtCore.Slot(str, float)
    def on_event(self, event, value):
        self.controller_event('default', event, value)

    def controller_event(self, controller, event, value):
        pressed = self.controller_pressed.setdefault(controller, set())
        if value <= .5:
            pressed.discard(event)
            return
        if event in pressed:
            return
        pressed.add(event)
        if event in ('ui_quick', 'ui_up', 'ui_down', 'ui_left', 'ui_right',
                     'ui_accept', 'ui_back', 'ui_l1', 'ui_r1'):
            self.input_family.emit(self.target_families.get(controller, 'playstation'))
        print(f'Controller event: {event}', flush=True)
        self.action.emit(event)

    def close(self):
        if hasattr(self, 'timer'):
            self.timer.stop()
        self.release_controller()


class DemoGame(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Overlay test underlay')
        self.count = 0
        self.label = QtWidgets.QLabel('Test underlay\nX key count: 0\nPress F8 to open the overlay', self)
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        layout = QtWidgets.QVBoxLayout(self); layout.addWidget(self.label)
        self.setStyleSheet('background:#18283c; color:white; font-size:30px;')
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.toggle = None

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_F8 and self.toggle:
            self.toggle()
        elif event.key() == QtCore.Qt.Key_X:
            self.count += 1
            self.label.setText(f'Test underlay\nX key count: {self.count}\nPress F8 to open the overlay')
            print(f'Underlay X count: {self.count}', flush=True)


ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def application_icon():
    icon = QtGui.QIcon()
    for size in (24, 48, 256):
        icon.addFile(str(ASSETS / 'logo' / f'hstn-rocket-{size}.png'), QtCore.QSize(size, size))
    return icon


class DestinationButton(QtWidgets.QPushButton):
    """A native button with uncropped doorway art and live destination text."""
    def __init__(self, name, target, parent=None):
        super().__init__(name, parent)
        self.target = target
        self.current = False
        self.art = QtGui.QPixmap(str(ASSETS / 'artwork' / f'switch-to-{target}-icon.png'))
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.setMinimumSize(0, 0)

    def minimumSizeHint(self):
        return QtCore.QSize(0, 0)

    def paintEvent(self, event):
        if self.property('action'):
            return super().paintEvent(event)
        painter = QtGui.QPainter(self)
        option = QtWidgets.QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ''
        self.style().drawControl(QtWidgets.QStyle.CE_PushButton, option, painter, self)
        margin = max(10, int(self.width() * .05))
        font = self.font()
        ratio = .075 if self.text().startswith('Switch to ') else .10
        font.setPixelSize(max(15, min(36, int(self.width() * ratio))))
        font.setBold(True)
        name_height = QtGui.QFontMetrics(font).height()
        badge_font = QtGui.QFont(font)
        badge_font.setPixelSize(max(12, int(font.pixelSize() * .65)))
        badge_height = QtGui.QFontMetrics(badge_font).height()
        # Reserve the same badge slot on all cards so destination names align.
        bottom_padding = max(12, margin)
        badge_gap = max(3, int(self.width() * .015))
        label_top = self.height() - bottom_padding - badge_height - badge_gap - name_height
        image_label_gap = max(12, int(self.width() * .045))
        area = QtCore.QRect(margin, margin, self.width()-2*margin,
                           max(1, label_top-image_label_gap-margin))
        art = self.art.scaled(area.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        painter.drawPixmap(area.center() - art.rect().center(), art)
        painter.setPen(QtGui.QColor('#FFF5E2'))
        painter.setFont(font)
        label = QtCore.QRect(margin, label_top, self.width()-2*margin, name_height)
        name = self.text() if self.text().startswith('Switch to ') else self.text().upper()
        painter.drawText(label, QtCore.Qt.AlignCenter, name)
        if self.current:
            painter.setFont(badge_font)
            badge = QtCore.QRect(margin, label.bottom()+1+badge_gap,
                                 self.width()-2*margin, badge_height)
            painter.drawText(badge, QtCore.Qt.AlignCenter, 'Current')


class ControllerConnections(QtCore.QObject):
    changed = QtCore.Signal(str, str, bool)

    def __init__(self, snapshot=controllers.physical_controllers):
        super().__init__()
        self.snapshot = snapshot
        self.previous = snapshot()  # Existing devices at startup are not hotplug.
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)

    def refresh(self):
        current = self.snapshot()
        for parent in sorted(self.previous.keys() - current.keys()):
            device = self.previous[parent]
            self.changed.emit(device['name'], device['transport'], False)
        for parent in sorted(current.keys() - self.previous.keys()):
            device = current[parent]
            self.changed.emit(device['name'], device['transport'], True)
        self.previous = current


class ControllerToast(QtWidgets.QFrame):
    """A small, non-interactive notification window, separate from the menu."""
    def __init__(self, desktop=False):
        super().__init__()
        self.desktop = desktop
        self.opacity = 0.8
        if desktop:
            self.setWindowOpacity(self.opacity)
        self.pending = []
        self.setWindowTitle('HSTN — Controller notification')
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint |
                            QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.WindowDoesNotAcceptFocus |
                            QtCore.Qt.WindowTransparentForInput)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setStyleSheet('QLabel {color:#FFF5E2; border:0; background:transparent;}')
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        self.rocket = QtWidgets.QLabel()
        self.rocket.setFixedSize(34, 34)
        self.rocket.setPixmap(QtGui.QPixmap(str(ASSETS / 'logo/hstn-rocket-48.png')).scaled(
            34, 34, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        self.rocket.setAccessibleName('HSTN')
        layout.addWidget(self.rocket)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet('font-size:16px; font-weight:600;')
        layout.addWidget(self.message, 1)
        self.transport = QtWidgets.QLabel()
        self.transport.setFixedSize(24, 24)
        layout.addWidget(self.transport)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self.advance)

    def paintEvent(self, event):
        # The window itself must have transparent corners; stylesheet rounding
        # alone leaves the native rectangular surface visible beneath it.
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor('#07172E'))
        painter.drawRoundedRect(QtCore.QRectF(self.rect()), 16, 16)

    @QtCore.Slot(str, str, bool)
    def notify(self, name, transport, connected):
        self.pending = (self.pending + [(name, transport, connected)])[-6:]
        if not self.timer.isActive():
            self.advance()

    def advance(self):
        self.dismiss()
        if not self.pending:
            return
        name, transport, connected = self.pending.pop(0)
        text = name + (' connected' if connected else ' disconnected')
        self.message.setText(name + ('\nConnected' if connected else '\nDisconnected'))
        self.transport.setPixmap(QtGui.QIcon(str(ASSETS / 'controller' / (transport + '.svg'))).pixmap(24, 24))
        self.transport.setAccessibleName('Bluetooth' if transport == 'bluetooth' else 'USB')
        self.setAccessibleName(text + ', ' + self.transport.accessibleName())
        screen = QtWidgets.QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.setFixedSize(min(360, max(180, area.width() - 48)), 76)
        self.move(area.right() - self.width() - 23, area.bottom() - self.height() - 23)
        if not self.desktop:
            try:
                # Gamescope treats a small overlay with no input focus as a
                # notification. Tag before mapping to avoid a game-focus change.
                window = int(self.winId())
                xproperty(window, 'STEAM_INPUT_FOCUS', 0)
                xproperty(window, 'STEAM_OVERLAY', 1)
                xproperty(window, '_NET_WM_WINDOW_OPACITY', round(self.opacity * 0xffffffff))
            except Exception as error:
                print(f'Controller notification tagging failed: {error}', file=sys.stderr)
                return
        self.show()
        self.timer.start()

    def dismiss(self):
        self.timer.stop()
        if self.isVisible() and not self.desktop:
            try:
                xproperty(int(self.winId()), '_NET_WM_WINDOW_OPACITY', 0)
                xproperty(int(self.winId()), 'STEAM_OVERLAY', 0)
            except Exception as error:
                print(f'Controller notification cleanup failed: {error}', file=sys.stderr)
        self.hide()


class ControllerFooter(QtWidgets.QWidget):
    """Center prompt images and text in native layout cells, without HTML baselines."""
    def __init__(self):
        super().__init__()
        self.glyphs = {}
        self.labels = {}
        self.rows = []
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        self.scroll = QtWidgets.QWidget()
        scroll_row = QtWidgets.QHBoxLayout(self.scroll)
        scroll_row.setContentsMargins(0, 0, 0, 0)
        self.add_glyph(scroll_row, 'l1')
        scroll_row.addWidget(QtWidgets.QLabel('/'))
        self.add_glyph(scroll_row, 'r1')
        scroll_row.addWidget(QtWidgets.QLabel('Scroll apps ·'))
        row.addWidget(self.scroll)
        self.rows.extend((row, scroll_row))
        for name, text in (('cross', 'Select'), ('circle', 'Back')):
            prompt = QtWidgets.QWidget()
            prompt_row = QtWidgets.QHBoxLayout(prompt)
            prompt_row.setContentsMargins(0, 0, 0, 0)
            self.add_glyph(prompt_row, name)
            self.labels[name] = QtWidgets.QLabel(text)
            prompt_row.addWidget(self.labels[name])
            row.addWidget(prompt)
            self.rows.append(prompt_row)

    def add_glyph(self, row, name):
        label = QtWidgets.QLabel()
        label.setAlignment(QtCore.Qt.AlignCenter)
        row.addWidget(label)
        self.glyphs[name] = label

    def configure(self, review, size, family='keyboard'):
        self.scroll.setVisible(review)
        for row in self.rows:
            row.setSpacing(max(3, size//6))
        names = {
            'playstation': ('l1', 'r1', 'cross', 'circle'),
            'xbox': ('xbox-lb', 'xbox-rb', 'xbox-a', 'xbox-b'),
            'keyboard': ('keyboard-page-up', 'keyboard-page-down', 'keyboard-enter', 'keyboard-escape'),
        }[family]
        for (name, label), asset in zip(self.glyphs.items(), names):
            label.setFixedSize(size, size)
            label.setPixmap(QtGui.QIcon(str(ASSETS / f'controller/{asset}.svg')).pixmap(size, size))
        scroll, accept, back = {
            'playstation': ('L1 or R1', 'Cross', 'Circle'),
            'xbox': ('LB or RB', 'A', 'B'),
            'keyboard': ('Page Up or Page Down', 'Enter', 'Escape'),
        }[family]
        self.setAccessibleName((scroll + ': scroll apps. ' if review else '') +
                               accept + ': select. ' + back + ': back.')



class Overlay(QtWidgets.QWidget):
    def __init__(self, router=None, underlay=None, enable_actions=True, desktop=False):
        super().__init__()
        self.router, self.underlay = router, underlay
        self.input_family = 'keyboard'
        self.enable_actions = enable_actions
        self.desktop = desktop
        self.request = SwitchRequest(self)
        self.request.completed.connect(self.switch_finished)
        close_helper = Path.home() / '.local/bin/session-close'
        self.planner = SwitchRequest(self, helper=close_helper, output_limit=1024*1024)
        self.planner.completed.connect(self.plan_finished)
        self.closer = SwitchRequest(self, helper=close_helper)
        self.closer.completed.connect(self.switch_finished)
        self.mode = 'menu'
        self.pending_target = None
        self.plan_path = None
        self.setWindowTitle('HSTN — Session menu')
        self.setWindowIcon(application_icon())
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.selection = 0
        self.buttons = []
        self.current_session = 'desktop' if desktop else os.environ.get('SESSION_SWITCH_CURRENT_SESSION')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = QtWidgets.QFrame()
        self.panel.setObjectName('panel')
        self.inside = inside = QtWidgets.QVBoxLayout(self.panel)
        header = QtWidgets.QHBoxLayout()
        self.logo = QtWidgets.QLabel()
        self.logo_art = QtGui.QPixmap(str(ASSETS / 'logo/hstn-rocket-256.png'))
        self.logo.setAlignment(QtCore.Qt.AlignCenter)
        header.addWidget(self.logo)
        wordmark = QtWidgets.QLabel('HSTN')
        wordmark.setObjectName('wordmark')
        header.addWidget(wordmark)
        header.addStretch()
        inside.addLayout(header)
        line = QtWidgets.QFrame()
        line.setObjectName('divider')
        line.setFixedHeight(1)
        inside.addWidget(line)
        self.title = QtWidgets.QLabel('Switch session')
        self.title.setObjectName('title')
        inside.addWidget(self.title)
        self.subtitle = QtWidgets.QLabel('Save your progress first. These apps will be closed.')
        self.subtitle.setWordWrap(True)
        self.subtitle.hide()
        inside.addWidget(self.subtitle)
        self.body = QtWidgets.QHBoxLayout()
        self.deck = QtWidgets.QWidget()
        self.deck_layout = QtWidgets.QHBoxLayout(self.deck)
        self.deck_layout.setContentsMargins(0, 0, 0, 0)
        self.menu_names = ('Steam', 'Heroic', 'Desktop', 'Return to Desktop' if desktop else 'Return to game')
        for index, name in enumerate(self.menu_names):
            button = DestinationButton(name, ('steam', 'heroic', 'desktop', 'desktop')[index])
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.setMouseTracking(True)
            button.installEventFilter(self)
            button.clicked.connect(lambda checked=False, index=index: self.choose(index))
            button.current = button.target == self.current_session
            button.setAccessibleName(name + (' — Current' if button.current else ''))
            self.buttons.append(button)
            if index < 3:
                self.deck_layout.addWidget(button)
            else:
                button.setParent(self)
                button.hide()
        self.body.addWidget(self.deck)
        self.review_left = QtWidgets.QWidget()
        self.review_layout = QtWidgets.QVBoxLayout(self.review_left)
        self.review_layout.setContentsMargins(0, 0, 0, 0)
        self.review_left.hide()
        self.body.addWidget(self.review_left, 2)
        self.status = QtWidgets.QLabel('Review running apps before switching.' if enable_actions else 'Demo: session switching is disabled.')
        self.status.setWordWrap(True)
        self.status.setTextFormat(QtCore.Qt.PlainText)
        self.status.setAlignment(QtCore.Qt.AlignTop)
        self.status.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.status_scroll = QtWidgets.QScrollArea()
        self.status_scroll.setWidgetResizable(True)
        self.status_scroll.setWidget(self.status)
        self.status_scroll.setFocusPolicy(QtCore.Qt.NoFocus)
        self.destination = DestinationButton('Switch to Steam', 'steam')
        self.destination.setFocusPolicy(QtCore.Qt.NoFocus)
        self.destination.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.destination.hide()
        self.body.addWidget(self.destination)
        inside.addLayout(self.body, 1)
        inside.addWidget(self.status_scroll)
        self.actions = QtWidgets.QHBoxLayout()
        inside.addLayout(self.actions)
        line = QtWidgets.QFrame()
        line.setObjectName('divider')
        line.setFixedHeight(1)
        inside.addWidget(line)
        self.footer = ControllerFooter()
        inside.addWidget(self.footer)
        layout.addWidget(self.panel, alignment=QtCore.Qt.AlignCenter)
        self.resize(1280, 800)
        self.update_metrics()
        if router:
            router.input_family.connect(self.set_input_family)
            router.action.connect(self.controller)

    def update_metrics(self):
        # Bound the panel in logical pixels rather than growing with a desktop monitor.
        panel_width = min(960, int(self.width() * .88))
        panel_height = min(620, int(self.height() * .86))
        scale = min(panel_width / 1126, panel_height / 688)
        unit = lambda value: max(1, int(value * scale))
        self.panel.setFixedSize(panel_width, panel_height)
        self.inside.setContentsMargins(unit(36), unit(20), unit(36), unit(20))
        self.inside.setSpacing(unit(14))
        self.deck_layout.setSpacing(unit(14))
        self.body.setSpacing(unit(28))
        self.actions.setSpacing(unit(18))
        self.logo.setFixedSize(unit(48), unit(60))
        self.logo.setPixmap(self.logo_art.scaled(self.logo.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        self.update_footer(max(26, unit(40)))
        self.status_scroll.setMinimumWidth(0)
        self.status_scroll.setMinimumHeight(unit(48) if self.mode not in ('confirm', 'closing') else 0)
        self.status_scroll.setMaximumHeight(unit(68) if self.mode not in ('confirm', 'closing') else 16777215)
        for button in self.buttons:
            if button.property('action'):
                button.setFixedHeight(unit(68))
        self.setStyleSheet(f"""
            #panel {{background:#06152E; border-radius:{unit(16)}px;}}
            QLabel {{color:#FFF5E2; font-size:{max(14, unit(23))}px; background:transparent;}}
            #wordmark {{font-size:{unit(36)}px; font-weight:bold;}}
            #title {{font-size:{max(24, unit(54))}px; font-weight:bold;}}
            #divider {{background:#526071; border:none;}}
            QPushButton {{background:#07182F; color:#FFF5E2;
                border-radius:{unit(16)}px; font-size:{max(16, unit(28))}px; font-weight:bold;}}
            QPushButton[destructive="true"] {{color:#FFD15A;}}
            QPushButton[selected="true"] {{border:{max(3, unit(5))}px solid #FFF5E2;}}
            QPushButton:disabled {{color:#9DA7B5; border-color:#233951;}}
            QScrollArea, QScrollArea QWidget {{background:transparent; border:none;}}
            QScrollBar:vertical {{background:#102440; width:{unit(12)}px;}}
            QScrollBar::handle:vertical {{background:#8191A8; min-height:20px;}}
        """)

    def set_input_family(self, family):
        if family in ('keyboard', 'xbox', 'playstation') and family != self.input_family:
            self.input_family = family
            self.update_footer()

    def update_footer(self, size=None):
        if size is None:
            scale = min(self.panel.width() / 1126, self.panel.height() / 688)
            size = max(26, int(40 * scale))
        self.footer.configure(self.mode in ('confirm', 'closing'), size, self.input_family)

    def resizeEvent(self, event):
        self.update_metrics()
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter=QtGui.QPainter(self);painter.fillRect(self.rect(),QtGui.QColor(0,0,0,150))

    def toggle(self):
        self.hide_overlay() if self.isVisible() else self.open_overlay()

    def open_overlay(self):
        if self.isVisible():
            self.raise_();self.activateWindow()
            return
        self.setGeometry(QtWidgets.QApplication.primaryScreen().geometry())
        if self.router:
            try:
                self.router.capture(True)
            except RuntimeError as error:
                if not self.desktop:
                    raise
                self.disable_controller(str(error))
        self.show()
        try:
            if self.desktop:
                self.raise_();self.activateWindow();self.setFocus();self.highlight()
                print('Desktop overlay opened', flush=True)
                return
            xproperty(int(self.winId()), 'STEAM_OVERLAY', 1)
            xproperty(int(self.winId()), '_NET_WM_WINDOW_OPACITY', 0xffffffff)
            xproperty(int(self.winId()), 'STEAM_INPUT_FOCUS', 1)
        except Exception as error:
            self.status.setText(f'X11 overlay tagging failed: {error}')
        self.raise_();self.activateWindow();self.setFocus();self.highlight()
        print(f'Overlay opened, window {int(self.winId())}', flush=True)

    def hide_overlay(self):
        if self.mode in ('confirm', 'planning'):
            self.cancel_review()
        if self.isVisible():
            try:
                if not self.desktop:
                    xproperty(int(self.winId()), 'STEAM_INPUT_FOCUS', 0)
                # Explicitly stop compositing the last overlay frame before unmapping.
                    xproperty(int(self.winId()), '_NET_WM_WINDOW_OPACITY', 0)
                    xproperty(int(self.winId()), 'STEAM_OVERLAY', 0)
            finally:
                self.hide()
                if self.router:
                    self.router.capture(False)
        if self.underlay:
            self.underlay.raise_();self.underlay.activateWindow();self.underlay.setFocus()
            self.underlay.repaint()
        print('Overlay closed; input released', flush=True)

    def disable_controller(self, message):
        # A queued guard failure can arrive after Open already recovered. Do not
        # hide the keyboard/mouse fallback a second time.
        router, self.router = self.router, None
        if router:
            try:
                self.hide_overlay()
            finally:
                router.input_family.disconnect(self.set_input_family)
                router.action.disconnect(self.controller)
                router.close()
        self.status.setText('Controller unavailable: ' + message + '\nUse mouse or keyboard to access HSTN.')

    def active_indices(self):
        return [index for index, button in enumerate(self.buttons) if not button.isHidden() and button.isEnabled()]

    def discard_plan(self, path):
        if not path:
            return
        candidate = Path(path)
        directory = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'session-switch-confirmations'
        if candidate.parent.resolve() == directory.resolve() and candidate.name.startswith('close-'):
            candidate.unlink(missing_ok=True)

    def reset_menu(self):
        self.mode = 'menu'
        self.pending_target = None
        self.plan_path = None
        self.title.setText('Switch session')
        self.update_footer()
        self.subtitle.hide()
        self.destination.hide()
        self.review_left.hide()
        self.inside.insertWidget(2, self.title)
        self.inside.insertWidget(3, self.subtitle)
        self.title.show()
        self.deck.show()
        self.inside.insertWidget(5, self.status_scroll)
        self.status.setTextFormat(QtCore.Qt.PlainText)
        for index, button in enumerate(self.buttons[:3]):
            button.setProperty('action', False)
            button.setProperty('destructive', False)
            button.setMaximumHeight(16777215)
            button.setMinimumHeight(0)
            self.deck_layout.addWidget(button)
            button.setAccessibleName(self.menu_names[index] + (' — Current' if button.current else ''))
        for index, name in enumerate(self.menu_names):
            self.buttons[index].setText(name)
            self.buttons[index].setEnabled(True)
            self.buttons[index].setVisible(index < 3)
        self.selection = 0
        self.update_metrics()
        self.highlight()

    def cancel_review(self):
        self.discard_plan(self.plan_path)
        self.reset_menu()
        self.status.setText('Cancelled. Your apps are still running.')

    def choose(self, index):
        if index == 3 and self.mode == 'menu':
            self.hide_overlay()
            return
        if index not in self.active_indices() or not self.buttons[index].isEnabled():
            return
        self.selection = index
        if not self.enable_actions:
            if index == 3:
                self.hide_overlay()
            else:
                self.status.setText('Demo: session switching is disabled.')
            return
        if self.mode == 'confirm':
            if index == 1:
                self.cancel_review()
            elif index == 0:
                self.mode = 'closing'
                for button in self.buttons:
                    button.setEnabled(False)
                self.status.setText('Closing the confirmed apps, then checking whether switching is allowed…')
                self.closer.start(self.pending_target, arguments=['execute', self.plan_path])
            return
        if index == 3 or (self.desktop and index == 2 and self.mode == 'menu'):
            self.hide_overlay()
            return
        if self.mode in ('closing', 'switching'):
            return
        if self.mode == 'menu' and not self.planner.busy and not self.request.busy:
            self.pending_target = ('steam', 'heroic', 'desktop')[index]
            self.mode = 'planning'
            self.status.setText('Checking running games and related launchers…')
            for button in self.buttons[:3]:
                button.setEnabled(False)
            self.planner.start(self.pending_target, arguments=['plan', self.pending_target])

    def plan_finished(self, code, output):
        try:
            plan = json.loads(output) if code == 0 else None
        except ValueError:
            plan = None
        if self.mode != 'planning':
            if plan:
                self.discard_plan(plan.get('path'))
            return
        if plan is None:
            self.switch_finished(code or 21, output or 'Could not inspect running apps.')
            return
        if not plan['apps']:
            self.mode = 'switching'
            self.status.setText('HSTN: checking running games…')
            self.request.start(self.pending_target)
            return
        self.mode = 'confirm'
        self.plan_path = plan['path']
        self.title.setText('Close and switch?')
        self.deck.hide()
        self.review_layout.addWidget(self.title)
        self.review_layout.addWidget(self.subtitle)
        self.review_layout.addWidget(self.status_scroll, 1)
        self.title.show()
        self.subtitle.show()
        self.status_scroll.show()
        self.review_left.show()
        self.destination.target = self.pending_target
        self.destination.art = QtGui.QPixmap(str(ASSETS / 'artwork' / f'switch-to-{self.pending_target}-icon.png'))
        self.destination.setText('Switch to ' + self.pending_target.title())
        self.body.setStretchFactor(self.destination, 1)
        self.destination.show()
        lines = []
        for app in plan['apps']:
            names = ', '.join(sorted({process['name'] for process in app['processes']}))
            lines.append(f"<p><big><b>{html.escape(app['label'])}</b></big><br><small>Process details: {html.escape(names)}</small></p>")
        if plan.get('warnings'):
            lines.append('<p>Some processes could not be identified. They will not be force-closed.</p>')
        self.status.setTextFormat(QtCore.Qt.RichText)
        self.status.setText(''.join(lines))
        self.status_scroll.verticalScrollBar().setValue(0)
        for index, button in enumerate(self.buttons):
            button.setEnabled(True)
            button.setVisible(index < 2)
            if index < 2:
                button.setProperty('action', True)
                button.setProperty('destructive', index == 0)
                self.actions.addWidget(button)
                button.show()
        self.buttons[0].setText('Close and switch')
        self.buttons[1].setText('Cancel')
        self.buttons[0].setAccessibleName('Close and switch')
        self.buttons[1].setAccessibleName('Cancel')
        self.update_footer()
        self.update_metrics()
        self.selection = 1  # Cancellation is the default.
        self.highlight()

    def switch_finished(self, code, output):
        self.discard_plan(self.plan_path)
        self.reset_menu()
        if code == 20:
            message = 'Switch blocked. Close remaining apps and try again.'
        elif code == 24:
            message = 'Running apps changed. Select the session to review them again.'
        elif code:
            message = f'Session switch failed (exit {code}).'
        else:
            message = 'Session switch requested.'
        if output:
            message += '\n' + '\n'.join(output.splitlines()[-3:])[-220:]
        self.status.setText(message)
        print(message, flush=True)

    def cancel_or_hide(self):
        if self.mode == 'confirm':
            self.cancel_review()
        else:
            self.hide_overlay()

    def scroll_details(self, direction):
        bar = self.status_scroll.verticalScrollBar()
        bar.setValue(bar.value() + direction * bar.pageStep())

    def highlight(self):
        for index, button in enumerate(self.buttons):
            button.setProperty('selected', index == self.selection)
            button.style().unpolish(button);button.style().polish(button)

    def eventFilter(self, watched, event):
        if event.type() in (QtCore.QEvent.Enter, QtCore.QEvent.MouseMove):
            if watched in self.buttons and watched.isEnabled() and not watched.isHidden():
                index = self.buttons.index(watched)
                if self.selection != index:
                    self.selection = index
                    self.highlight()
        return super().eventFilter(watched, event)

    def navigate(self, direction):
        indices = self.active_indices()
        if not indices:
            return
        current = indices.index(self.selection) if self.selection in indices else 0
        self.selection = indices[(current+direction)%len(indices)]
        self.highlight()

    def controller(self, event):
        if event == 'ui_quick':self.toggle()
        elif self.isVisible():
            if event in ('ui_down','ui_right'):self.navigate(1)
            elif event in ('ui_up','ui_left'):self.navigate(-1)
            elif event == 'ui_accept':self.choose(self.selection)
            elif event == 'ui_back':self.cancel_or_hide()
            elif event == 'ui_l1':self.scroll_details(-1)
            elif event == 'ui_r1':self.scroll_details(1)

    def event(self, event):
        if event.type() == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            self.set_input_family('keyboard')
            self.navigate(-1 if event.key() == QtCore.Qt.Key_Backtab or event.modifiers() & QtCore.Qt.ShiftModifier else 1)
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Escape, QtCore.Qt.Key_F8, QtCore.Qt.Key_PageUp,
                           QtCore.Qt.Key_PageDown, QtCore.Qt.Key_Down, QtCore.Qt.Key_Right,
                           QtCore.Qt.Key_Up, QtCore.Qt.Key_Left, QtCore.Qt.Key_Return,
                           QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space, QtCore.Qt.Key_Tab):
            self.set_input_family('keyboard')
        if event.key() in (QtCore.Qt.Key_Escape,QtCore.Qt.Key_F8):self.cancel_or_hide()
        elif event.key() == QtCore.Qt.Key_PageUp:self.scroll_details(-1)
        elif event.key() == QtCore.Qt.Key_PageDown:self.scroll_details(1)
        elif event.key() in (QtCore.Qt.Key_Down,QtCore.Qt.Key_Right):self.navigate(1)
        elif event.key() in (QtCore.Qt.Key_Up,QtCore.Qt.Key_Left):self.navigate(-1)
        elif event.key() in (QtCore.Qt.Key_Return,QtCore.Qt.Key_Enter,QtCore.Qt.Key_Space):self.choose(self.selection)
        elif event.key() == QtCore.Qt.Key_Tab:self.navigate(-1 if event.modifiers() & QtCore.Qt.ShiftModifier else 1)

    def closeEvent(self, event):
        self.hide_overlay();event.ignore()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--manage-input',action='store_true')
    parser.add_argument('--controller',action='store_true',help='Use already managed InputPlumber controller')
    parser.add_argument('--timeout',type=int,default=90,help='Auto-exit seconds; 0 runs until stopped')
    parser.add_argument('--start-hidden',action='store_true',help='Wait in background for PS + Create/Select')
    parser.add_argument('--desktop',action='store_true',help='KDE Desktop session menu with native focus restoration')
    parser.add_argument('--self-test',action='store_true',help='Automated keyboard/focus demo; no controller required')
    args=parser.parse_args()
    if args.desktop and args.demo:
        parser.error('--desktop and --demo cannot be combined')
    lease = None
    focus = None
    endpoint = None
    support = None
    if args.desktop or (not args.demo and (args.controller or args.manage_input)):
        spec = importlib.util.spec_from_file_location('desktop_overlay_support',
            Path(__file__).resolve().parents[1] / 'scripts/desktop-overlay-support.py')
        support = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(support)
        try:
            lease = support.OverlayLease(Path(os.environ['XDG_RUNTIME_DIR']))
        except (KeyError, OSError, RuntimeError) as error:
            print(error, file=sys.stderr)
            return 1
    if args.desktop:
        if 'KDE' not in os.environ.get('XDG_CURRENT_DESKTOP', ''):
            print('Desktop overlay requires a KDE graphical session', file=sys.stderr)
            lease.close()
            return 1
        os.environ['SESSION_SWITCH_DESKTOP_MODE'] = '1'
        os.environ['SESSION_SWITCH_REQUIRE_INPUT_GUARD'] = '1'
    else:
        os.environ.pop('SESSION_SWITCH_DESKTOP_MODE', None)
    app=QtWidgets.QApplication(sys.argv[:1]);app.setQuitOnLastWindowClosed(False)
    app.setApplicationName('hstn-overlay')
    app.setApplicationDisplayName('HSTN')
    app.setDesktopFileName('hstn-open')
    app.setWindowIcon(application_icon())
    router=InputRouter(args.manage_input, lease) if args.controller or args.manage_input else None
    controller_error = None
    if router:
        try:router.start()
        except Exception as error:
            router.close();print(error,file=sys.stderr)
            if not args.desktop:
                if lease:lease.close()
                return 1
            controller_error = str(error)
            router = None
    underlay=DemoGame() if args.demo else None
    overlay=Overlay(router,underlay,enable_actions=not args.demo,desktop=args.desktop)
    connections = toast = None
    if router or args.desktop:
        toast = ControllerToast(desktop=args.desktop)
        connections = ControllerConnections()
        connections.changed.connect(toast.notify)
        connections.timer.start()
        app.aboutToQuit.connect(connections.timer.stop)
        app.aboutToQuit.connect(toast.dismiss)
    if controller_error:
        overlay.disable_controller(controller_error)
    if router:
        def input_failed(message):
            print(message, file=sys.stderr, flush=True)
            if args.desktop:
                QtCore.QTimer.singleShot(0, lambda: overlay.disable_controller(message))
            else:
                QtCore.QTimer.singleShot(0, app.quit)
        router.fatal.connect(input_failed)
    if args.desktop:
        try:
            focus = support.KWinFocus(os.environ['XDG_RUNTIME_DIR'], overlay.windowTitle())
            endpoint = support.DesktopEndpoint(overlay)
        except Exception as error:
            print(error, file=sys.stderr)
            if router:router.close()
            if focus:focus.close()
            lease.close()
            return 1
    if underlay:
        underlay.resize(1280,720);underlay.show()
        xproperty(int(underlay.winId()),'STEAM_GAME',424242)
        subprocess.run(['xprop','-root','-f','GAMESCOPECTRL_BASELAYER_APPID','32co',
                        '-set','GAMESCOPECTRL_BASELAYER_APPID','424242'],check=True,capture_output=True)
        underlay.toggle=overlay.toggle
        underlay.activateWindow();underlay.setFocus()
    elif not args.start_hidden:
        QtCore.QTimer.singleShot(100,overlay.open_overlay)
    app.aboutToQuit.connect(overlay.hide_overlay)
    if router:app.aboutToQuit.connect(router.close)
    if endpoint:app.aboutToQuit.connect(endpoint.close)
    if focus:app.aboutToQuit.connect(focus.close)
    if lease:app.aboutToQuit.connect(lease.close)
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *unused:app.quit())
    tick=QtCore.QTimer();tick.timeout.connect(lambda:None);tick.start(200)
    if args.timeout > 0:
        QtCore.QTimer.singleShot(max(5,args.timeout)*1000,app.quit)
    if args.self_test:
        if not underlay:parser.error('--self-test requires --demo')
        failures=[]
        def send(key):subprocess.run(['xdotool','key',key],check=True)
        def before():send('x')
        def opened():
            if underlay.count != 1:failures.append(f'Initial underlay input: {underlay.count}')
            overlay.open_overlay()
        def during():send('x');send('Down')
        def closed():
            if underlay.count != 1:failures.append('Keyboard leaked through overlay')
            if overlay.selection != 1:failures.append(f'Overlay navigation failed: {overlay.selection}')
            overlay.controller('ui_back')
            if overlay.isVisible():failures.append('Circle did not hide the menu')
        def reopened():overlay.open_overlay()
        def returned():
            overlay.choose(3)
            if overlay.isVisible():failures.append('Return to game did not hide the menu')
        def after():send('x')
        def finish():
            if underlay.count != 2:failures.append(f'Focus not restored: {underlay.count}')
            print(json.dumps({'keyboard_focus_test':'FAIL' if failures else 'PASS','failures':failures}),flush=True)
            app.exit(1 if failures else 0)
        for delay,callback in ((1500,before),(2200,opened),(3000,during),(3800,closed),(5000,reopened),(5600,returned),(6500,after),(7500,finish)):
            QtCore.QTimer.singleShot(delay,callback)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
