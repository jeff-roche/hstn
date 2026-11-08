#!/usr/bin/env python3
"""Read-only identity checks for the permanent input service."""
import json
from pathlib import Path
import stat

STATUS=Path('/run/session-switch-input-guard/active')


def permanent_guard_active(status=STATUS,proc=Path('/proc'),owner_uid=0):
    try:
        info=status.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner_uid or info.st_mode & 0o022:return False
        data=json.loads(status.read_text())
        if data.get('version')!=1 or data.get('kind')!='session-switch-input-guard':return False
        pid=data['pid']
        if not isinstance(pid,int) or pid<=1:return False
        process=proc/str(pid)
        if process.stat().st_uid!=owner_uid:return False
        fields=(process/'stat').read_text().rsplit(') ',1)[1].split()
        return fields[0] not in ('Z','X') and int(fields[19])==data['start_ticks']
    except (OSError,ValueError,KeyError,TypeError,IndexError):return False


def legacy_guard_active(path=Path('/run/session-switch-input-diagnostic.active'),proc=Path('/proc')):
    """Compatibility only while migrating old temporary test instructions."""
    try:
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:return False
        pid=int(path.read_text().strip())
        if pid<=1 or (proc/str(pid)).stat().st_uid!=0:return False
        return (proc/str(pid)/'stat').read_text().rsplit(') ',1)[1].split()[0] not in ('Z','X')
    except (OSError,ValueError,IndexError):return False
