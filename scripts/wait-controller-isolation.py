#!/usr/bin/env python3
"""Verify the input guard and controller isolation before a gaming session."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys
import time


def main(timeout=60, single_playstation=False):
    status_spec = importlib.util.spec_from_file_location('input_guard_status', Path(__file__).resolve().with_name('input-guard-status.py'))
    status = importlib.util.module_from_spec(status_spec)
    status_spec.loader.exec_module(status)
    def guard_active():
        return status.permanent_guard_active() or status.legacy_guard_active()
    if not guard_active():
        print('Input guard is unavailable. Start session-switch-input-guard.service.', flush=True)
        return 1
    spec = importlib.util.spec_from_file_location('routes', Path(__file__).resolve().with_name('controller-route-snapshot.py'))
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    deadline = time.monotonic() + timeout
    stable = 0
    while time.monotonic() < deadline:
        report = {'routes': routes.device_routes(), 'inputplumber': routes.inputplumber_state()}
        issues = routes.isolation_issues(report, single_playstation=single_playstation)
        if not guard_active():
            issues.append('Input guard stopped')
        if issues:
            stable = 0
            print('Waiting for input isolation: ' + '; '.join(issues), flush=True)
        else:
            stable += 1
            if stable >= 2:
                print('Physical input exclusion verified before launcher startup.', flush=True)
                return 0
        time.sleep(1)
    print('Input isolation timed out; custom overlay will be stopped.', flush=True)
    return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--single-playstation', action='store_true')
    args = parser.parse_args()
    sys.exit(main(single_playstation=args.single_playstation))
