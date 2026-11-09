"""Read Steam's persisted Gaming Mode display scale without modifying settings."""
import math
import os
from pathlib import Path
import re

TOKEN = re.compile(r'\s+|//[^\n]*|"((?:\\.|[^"\\])*)"|([{}])')
CURRENT_DISPLAY = ('InstallConfigStore', 'UI', 'display', 'Current')
MAX_CONFIG_BYTES = 4 * 1024 * 1024


def display_scale(text):
    """Extract the display scale; magnifier and Desktop accessibility are separate."""
    values = {}
    def tokens():
        position = 0
        for match in TOKEN.finditer(text):
            if match.start() != position:
                raise ValueError('Malformed Steam settings')
            position = match.end()
            if match[1] is not None:
                yield 'string', re.sub(r'\\(["\\])', r'\1', match[1])
            elif match[2]:
                yield 'brace', match[2]
        if position != len(text):
            raise ValueError('Malformed Steam settings')
    stream = iter(tokens())
    def block(path=(), closing=False):
        if len(path) > 32:
            raise ValueError('Steam settings nesting is too deep')
        for kind, key in stream:
            if (kind, key) == ('brace', '}') and closing:
                return
            if kind != 'string':
                raise ValueError('Expected a Steam settings key')
            try:
                kind, value = next(stream)
            except StopIteration:
                raise ValueError('Incomplete Steam settings') from None
            if (kind, value) == ('brace', '{'):
                block(path + (key,), True)
            elif kind == 'string':
                if path == CURRENT_DISPLAY and key in ('ScaleFactor', 'AutoScaleFactor'):
                    if key in values:
                        raise ValueError('Duplicate Steam display scale')
                    values[key] = value
            else:
                raise ValueError('Expected a Steam settings value')
        if closing:
            raise ValueError('Incomplete Steam settings block')
    try:
        block()
        for name in ('ScaleFactor', 'AutoScaleFactor'):
            value = float(values.get(name, 0))
            if math.isfinite(value) and .5 <= value <= 4:
                return value
    except (ValueError, TypeError, RecursionError):
        pass
    return None


class SteamUIScale:
    """Poll changes cheaply, keeping the last valid scale during incomplete writes."""
    def __init__(self, home=None, data_home=None):
        home = Path(home) if home is not None else Path.home()
        data_home = Path(data_home) if data_home is not None else Path(os.environ.get('XDG_DATA_HOME', home/'.local/share'))
        self.paths = [home/'.steam/steam/config/config.vdf',
                      home/'.steam/root/config/config.vdf', data_home/'Steam/config/config.vdf']
        self.signature = None
        self.scale = 1.0

    def poll(self):
        for path in self.paths:
            try:
                info = path.stat()
                signature = (str(path), info.st_ino, info.st_mtime_ns, info.st_size)
                if signature == self.signature:
                    return self.scale
                if info.st_size > MAX_CONFIG_BYTES:
                    continue
                with path.open('rb') as stream:
                    data = stream.read(MAX_CONFIG_BYTES + 1)
                if len(data) > MAX_CONFIG_BYTES:
                    continue
                value = display_scale(data.decode('utf-8'))
                self.signature = signature
                if value is not None:
                    self.scale = value
                return self.scale
            except (OSError, UnicodeError):
                continue
        return self.scale
