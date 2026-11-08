#!/usr/bin/env python3
"""Register normal unregistered Wine windows in standalone Heroic Gamescope."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import signal
import subprocess
import time

APP_ID = 600124


def is_candidate(window):
    props = window['properties']
    text = props['output']
    if props['status'] or not re.search(r'^WM_CLASS.*"steam_app_0"', text, re.M):
        return False
    if 'notification' in text.lower() or re.search(r'window state: (Iconic|Withdrawn)', text):
        return False
    # Fullscreen Wine games may omit WM_STATE entirely. Actual visibility and
    # dimensions are checked via xwininfo before any registration.
    if 'window state: Normal' not in text and not re.search(r'^(?:_NET_WM_NAME|WM_NAME).* = \"[^\"]+\"', text, re.M):
        return False
    if re.search(r'^STEAM_OVERLAY.*=\s*1\b', text, re.M):
        return False
    app = re.search(r'^STEAM_GAME.*=\s*(\d+)', text, re.M)
    return app is None or int(app[1]) in (0, APP_ID)


def desired_layers(current, active):
    if current not in ([1], [APP_ID, 1]):
        return None  # Another helper owns selection; do not overwrite it.
    return [APP_ID, 1] if active else [1]


def xprop(*args):
    return subprocess.run(['xprop', *args], capture_output=True, text=True, check=True, timeout=2).stdout


def layers():
    text = xprop('-root', 'GAMESCOPECTRL_BASELAYER_APPID')
    return [int(n) for n in re.findall(r'\d+', text.split('=', 1)[1])] if '=' in text else []


def select(values):
    xprop('-root', '-f', 'GAMESCOPECTRL_BASELAYER_APPID', '32co', '-set',
          'GAMESCOPECTRL_BASELAYER_APPID', ','.join(map(str, values)))


class Focus:
    def __init__(self):
        spec = importlib.util.spec_from_file_location('window_probe', Path(__file__).resolve().with_name('collect-gamescope-windows.py'))
        self.probe = importlib.util.module_from_spec(spec);spec.loader.exec_module(self.probe)
        self.tagged = {}

    def tick(self):
        active = False
        for window in self.probe.snapshot()['windows']:
            if not is_candidate(window):
                continue
            wid = window['id']
            info = window.get('statistics') or self.probe.query('xwininfo', '-id', wid, '-stats')
            if info['status'] or 'Map State: IsViewable' not in info['output']:
                continue
            width = re.search(r'Width:\s*(\d+)', info['output'])
            height = re.search(r'Height:\s*(\d+)', info['output'])
            if not width or not height or int(width[1]) < 100 or int(height[1]) < 100:
                continue
            tagged_value = re.search(r'^STEAM_GAME.*=\s*(\d+)', window['properties']['output'], re.M)
            if wid not in self.tagged or tagged_value is None or int(tagged_value[1]) != APP_ID:
                app = re.search(r'^STEAM_GAME.*=\s*(\d+)', window['properties']['output'], re.M)
                xprop('-id', wid, '-f', 'STEAM_GAME', '32c', '-set', 'STEAM_GAME', str(APP_ID))
                self.tagged[wid] = int(app[1]) if app else None
                print(f'Registered Wine window {wid} as {APP_ID}', flush=True)
            active = True
        current = layers()
        desired = desired_layers(current, active)
        if desired is not None and desired != current:
            select(desired)
            print(f'Heroic layer selection: {desired}', flush=True)

    def close(self):
        try:
            if layers() == [APP_ID, 1]:
                select([1])
        except (OSError, subprocess.SubprocessError):
            pass
        for wid, original in self.tagged.items():
            try:
                if f'= {APP_ID}' not in xprop('-id', wid, 'STEAM_GAME'):
                    continue
                if original is None:
                    xprop('-id', wid, '-remove', 'STEAM_GAME')
                else:
                    xprop('-id', wid, '-f', 'STEAM_GAME', '32c', '-set', 'STEAM_GAME', str(original))
            except (OSError, subprocess.SubprocessError):
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=int, required=True)
    args = parser.parse_args()
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop);signal.signal(signal.SIGINT, stop)
    focus = Focus()
    try:
        while running:
            try:
                os.kill(args.parent, 0)
            except ProcessLookupError:
                break
            try:
                focus.tick()
            except (OSError, subprocess.SubprocessError) as error:
                print(f'Heroic focus inspection: {error}', flush=True)
            time.sleep(0.75)
    finally:
        focus.close()


if __name__ == '__main__':
    main()
