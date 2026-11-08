#!/usr/bin/env python3
"""Read-only, bounded X11 window evidence for standalone Heroic sessions."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time


def query(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=2)
    return {'status': result.returncode, 'output': result.stdout[:16000], 'error': result.stderr[:500]}


def snapshot():
    tree = query('xwininfo', '-root', '-tree')
    ids = re.findall(r'^\s*(0x[0-9a-fA-F]+)\s', tree['output'], re.M)
    windows = []
    for wid in dict.fromkeys(ids):
        if len(windows) >= 48:
            break
        props = query('xprop', '-id', wid, 'WM_CLASS', '_NET_WM_NAME', 'WM_NAME',
                      '_NET_WM_PID', 'STEAM_GAME', 'STEAM_OVERLAY', 'WM_STATE')
        entry = {'id': wid, 'properties': props}
        if 'steam_app_0' in props['output']:
            entry['statistics'] = query('xwininfo', '-id', wid, '-stats')
        windows.append(entry)
    return {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'display': os.environ.get('DISPLAY'),
            'root': query('xprop', '-root', 'GAMESCOPECTRL_BASELAYER_APPID',
                          'GAMESCOPE_FOCUSED_WINDOW', 'GAMESCOPE_FOCUSED_APP',
                          'GAMESCOPE_FOCUSABLE_APPS'),
            'tree': tree, 'windows': windows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', type=int, required=True)
    parser.add_argument('--duration', type=int, default=900)
    args = parser.parse_args()
    os.umask(0o077)
    folder = Path.home()/'.local/state/session-switch/window-diagnostics'
    folder.mkdir(parents=True, exist_ok=True)
    filename = datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + f'-{os.getpid()}.jsonl'
    deadline = time.monotonic() + args.duration
    with (folder/filename).open('w') as stream:
        while time.monotonic() < deadline:
            try:
                os.kill(args.parent, 0)
            except ProcessLookupError:
                break
            try:
                report = snapshot()
            except (OSError, subprocess.SubprocessError) as error:
                report = {'error': str(error)}
            stream.write(json.dumps(report)+'\n');stream.flush()
            time.sleep(2)


if __name__ == '__main__':
    main()
