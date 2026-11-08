"""Shared overlay ownership, Desktop activation IPC and native KWin focus."""
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
from PySide6 import QtCore, QtDBus

SERVICE = 'org.hstn.DesktopOverlay'
OBJECT = '/Overlay'
INTERFACE = SERVICE


class OverlayLease:
    """The restore watchdog inherits this open description until cleanup ends."""
    def __init__(self, runtime):
        path = Path(runtime) / 'hstn-overlay.lock'
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        info = os.fstat(self.fd)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
            self.close()
            raise RuntimeError('Untrusted HSTN overlay lock')
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.close()
            raise RuntimeError('Another HSTN overlay owns controller routing; wait for its cleanup.') from None

    def fileno(self):
        return self.fd

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


@QtCore.ClassInfo(**{'D-Bus Interface': INTERFACE})
class DesktopEndpoint(QtCore.QObject):
    def __init__(self, menu):
        super().__init__(menu)
        self.menu = menu
        self.connection = QtDBus.QDBusConnection.sessionBus()
        if not self.connection.registerService(SERVICE):
            raise RuntimeError('Desktop HSTN is already running or session D-Bus is unavailable')
        if not self.connection.registerObject(OBJECT, self, QtDBus.QDBusConnection.ExportAllSlots):
            self.connection.unregisterService(SERVICE)
            raise RuntimeError('Could not expose HSTN Desktop activation')

    @QtCore.Slot(result=bool)
    def Open(self):
        self.menu.open_overlay()
        return True

    @QtCore.Slot(result=bool)
    def Hide(self):
        self.menu.hide_overlay()
        return True

    @QtCore.Slot(result=str)
    def Status(self):
        router = self.menu.router
        return json.dumps({'visible': self.menu.isVisible(),
                           'controller': bool(router and router.state['modes']),
                           'mode': 'desktop', 'pid': os.getpid()})

    def close(self):
        self.connection.unregisterObject(OBJECT)
        self.connection.unregisterService(SERVICE)


class KWinFocus:
    """One scoped KWin script; no persistent KWin settings or global shortcuts."""
    plugin = 'hstn-desktop-focus'

    def __init__(self, runtime, title):
        self.path = Path(runtime) / f'hstn-focus-{os.getpid()}.js'
        source = Path(__file__).resolve().parents[1] / 'templates/config/kwin/hstn-focus.js'
        content = source.read_text().replace('__HSTN_PID__', str(os.getpid())).replace('__HSTN_TITLE__', json.dumps(title))
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        try:
            # A prior crash can leave our own script loaded; never unload others.
            self.call('/Scripting', 'org.kde.kwin.Scripting.unloadScript', self.plugin)
            script = self.call('/Scripting', 'org.kde.kwin.Scripting.loadScript', str(self.path), self.plugin)
            if not script.isdigit():
                raise RuntimeError(f'KWin did not load HSTN focus bridge: {script}')
            self.call(f'/Scripting/Script{script}', 'org.kde.kwin.Script.run')
        except Exception:
            self.close()
            raise

    @staticmethod
    def call(path, method, *args):
        result = subprocess.run(['qdbus-qt6', 'org.kde.KWin', path, method, *args],
                                capture_output=True, text=True, timeout=3)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'KWin focus bridge call failed')
        return result.stdout.strip()

    def close(self):
        try:
            self.call('/Scripting', 'org.kde.kwin.Scripting.unloadScript', self.plugin)
        finally:
            self.path.unlink(missing_ok=True)
