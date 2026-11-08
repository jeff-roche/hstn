#!/usr/bin/env python3
"""Hold a brief, session-independent lid-switch inhibitor during a transition."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid


def start():
    # Notify comes from the holder child only AFTER systemd-inhibit acquired its
    # logind FD. The transient user service survives graphical-session teardown.
    arguments = [
        '/usr/bin/systemd-run','--user','--collect','--quiet','--no-ask-password',
        '--expand-environment=no','--unit=hstn-transition-lid-'+uuid.uuid4().hex,
        '--service-type=notify','--property=NotifyAccess=all',
        '--property=TimeoutStartSec=5s','--property=RuntimeMaxSec=40s',
        '--property=TimeoutStopSec=2s',
        '/usr/bin/python3','-B',str(Path(__file__).resolve()),'--inhibit']
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=8)
    if result.returncode:
        print(result.stderr.strip() or 'Could not acquire the transition lid inhibitor',file=sys.stderr)
    return result.returncode


def inhibit():
    address = os.environ.get('NOTIFY_SOCKET')
    if not address:
        raise RuntimeError('Missing user-service readiness socket')
    # systemd-inhibit clears NOTIFY_SOCKET before executing the holder. Preserve
    # the exact service-provided address, never guess the manager socket path.
    environment = dict(os.environ,HSTN_TRANSITION_NOTIFY_SOCKET=address)
    arguments = ['/usr/bin/systemd-inhibit','--no-ask-password','--what=handle-lid-switch',
        '--mode=block','--who=HSTN','--why=Protect the brief graphical session handoff',
        '/usr/bin/python3','-B',str(Path(__file__).resolve()),'--hold','--seconds','30']
    os.execve(arguments[0],arguments,environment)


def hold(seconds):
    if not 1 <= seconds <= 30:
        raise ValueError('Transition guard duration must be between 1 and 30 seconds')
    address = os.environ.get('HSTN_TRANSITION_NOTIFY_SOCKET') or os.environ.get('NOTIFY_SOCKET')
    if not address:
        raise RuntimeError('The transition holder must run inside its notifying user service')
    if address.startswith('@'):
        address = '\0' + address[1:]
    with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as notify:
        notify.sendto(b'READY=1\nSTATUS=Holding temporary lid-switch protection',address)
    time.sleep(seconds)
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('start',),nargs='?',default='start')
    parser.add_argument('--hold',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--inhibit',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--seconds',type=int,default=30,help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    try:
        if args.inhibit:
            inhibit()
            return 0
        return hold(args.seconds) if args.hold else start()
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        print(f'HSTN transition guard: {error}',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
