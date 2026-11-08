#!/usr/bin/env python3
"""Bounded, read-only route capture for a single gaming session."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', type=int, required=True)
    parser.add_argument('--duration', type=float, default=600)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('routes', Path(__file__).with_name('controller-route-snapshot.py'))
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    os.umask(0o077)
    folder = Path.home() / '.local/state/session-switch/diagnostics' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    folder.mkdir(parents=True)
    deadline = time.monotonic() + args.duration
    with (folder / 'routes.jsonl').open('w') as output:
        while True:
            try:
                os.kill(args.parent, 0)
            except ProcessLookupError:
                break
            report = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                      'routes': routes.device_routes(), 'inputplumber': routes.inputplumber_state()}
            output.write(json.dumps(report) + '\n')
            output.flush()
            if time.monotonic() >= deadline:
                break
            time.sleep(2)


if __name__ == '__main__':
    main()
