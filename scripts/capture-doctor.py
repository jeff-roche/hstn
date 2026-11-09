#!/usr/bin/env python3
"""Consume an explicitly armed one-session HSTN mechanic capture request."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode=True


def parent_alive(pid):
    try:
        fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(') ',1)[1].split()
        return fields[0] not in ('Z','X')
    except (OSError,IndexError):
        return False


def capture(session,parent,state=None,delay=5):
    state=state or Path.home()/'.local/state/hstn'
    marker=state/f'doctor-{session}.once'
    try:
        marker.unlink()
    except FileNotFoundError:
        return None
    folder=state/'doctor'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    now=datetime.datetime.now(datetime.timezone.utc)
    report={'version':1,'session':session,'timestamp_utc':now.isoformat(),
            'doctor_exit_code':None,'doctor':None,'error':None}
    time.sleep(delay)
    if not parent_alive(parent):
        report['error']='Gaming session ended before capture started'
    else:
        env=dict(os.environ,XDG_CURRENT_DESKTOP='gamescope',
                 SESSION_SWITCH_INPUT_TARGET=os.environ.get('SESSION_SWITCH_INPUT_TARGET','ds5-single'))
        try:
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve().with_name('mechanic.py')),'--json'],
                                  env=env,capture_output=True,text=True,timeout=60)
            report['doctor_exit_code']=result.returncode
            report['doctor']=json.loads(result.stdout)
            if not parent_alive(parent):
                report['error']='Gaming session ended during capture; do not treat this report as live-session validation'
        except subprocess.TimeoutExpired:
            report['error']='Doctor capture timed out after 60s'
        except (OSError,ValueError) as error:
            report['error']=f'Doctor capture failed: {error}'
    # Unique private reports preserve both successes and failed diagnostics.
    with tempfile.NamedTemporaryFile(mode='w',dir=folder,
            prefix=now.strftime('%Y%m%d-%H%M%S-')+session+'-',suffix='.json',delete=False) as stream:
        os.fchmod(stream.fileno(),0o600)
        json.dump(report,stream,indent=2)
        stream.write('\n')
        path=Path(stream.name)
    print(f'HSTN mechanic capture saved: {path}',flush=True)
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session',choices=('steam','heroic'),required=True)
    parser.add_argument('--parent',type=int,required=True)
    args=parser.parse_args()
    capture(args.session,args.parent)


if __name__=='__main__':
    main()
