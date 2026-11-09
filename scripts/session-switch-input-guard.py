#!/usr/bin/env python3
"""Maintain the narrow InputPlumber HID rule correction across sessions.

Installed as root-owned code under /usr/local/libexec. Reserves supported physical
sources before udev grants session access, including hotplug between sessions.
Never enables controller management or changes launcher settings.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import tempfile
import time

RULE_NAME=re.compile(r'(50|96)-inputplumber-hide-(hidraw[0-9]+)-(early|late)\.rules')
RUNTIME=Path('/run/session-switch-input-guard')
RULES=Path('/run/udev/rules.d')
SOURCE_RULE_NAME='72-hstn-controller-sources.rules'
# Run after 70-uaccess/71-seat, but before 73-seat-late grants the active user's
# ACL. Final permission assignments also prevent later vendor rules reopening
# the sources. Match HID ancestry, never reusable hidraw/event numbers. BlueZ
# UHID sources use bus 0005; InputPlumber's virtual USB outputs use bus 0003.
SOURCE_RULE='''# HSTN: reserve physical DualSense sources for root InputPlumber.
ACTION!="add|change", GOTO="hstn_sources_end"
SUBSYSTEM!="hidraw|input", GOTO="hstn_sources_end"
KERNEL!="hidraw*|event*|js*|mouse*", GOTO="hstn_sources_end"
DEVPATH=="/devices/virtual/*", KERNELS=="0003:054C:0CE6.*", GOTO="hstn_sources_end"
SUBSYSTEMS=="hid", KERNELS=="0003:054C:0CE6.*|0005:054C:0CE6.*", TAG-="uaccess", OWNER:="root", GROUP:="root", MODE:="0600"
LABEL="hstn_sources_end"
'''


def supported_source_paths(sysfs=Path('/sys')):
    paths=[]
    entries=[*sysfs.glob('class/hidraw/hidraw*'), *sysfs.glob('class/input/event*'),
             *sysfs.glob('class/input/js*'), *sysfs.glob('class/input/mouse*')]
    for entry in entries:
        device=(entry/'device').resolve()
        virtual=Path(sysfs)/'devices/virtual' in device.parents
        for parent in (device, *device.parents):
            if parent == Path(sysfs):break
            try:lines=(parent/'uevent').read_text().splitlines()
            except OSError:continue
            if ('HID_ID=0005:0000054C:00000CE6' in lines or
                    (not virtual and 'HID_ID=0003:0000054C:00000CE6' in lines)):
                paths.append(str(entry));break
    return paths


def refresh_sources():
    refresh_paths(supported_source_paths())


def correct_rule(text,node):
    lines=text.splitlines(keepends=True)
    for index,line in enumerate(lines):
        if (line.startswith('ACTION=="add|change", SUBSYSTEMS=="hidraw", ')
                and f'KERNEL=="{node}",' in line and 'KERNELS==' in line):
            lines[index]=line.replace('SUBSYSTEMS=="hidraw"','SUBSYSTEM=="hidraw"',1)
    return ''.join(lines)


def physical_node(node, sysfs=Path('/sys')):
    device = Path(sysfs)/'class/hidraw'/node/'device'
    if not device.exists():
        return False
    if Path(sysfs)/'devices/virtual' not in device.resolve().parents:
        return True
    # BlueZ physical Bluetooth sources can live under virtual/misc/uhid.
    # Keep USB-emulated HSTN outputs excluded. This root helper stays standalone.
    try:
        return 'HID_ID=0005:0000054C:00000CE6' in (device/'uevent').read_text().splitlines()
    except OSError:
        return False


def refresh_nodes(nodes):
    paths=[str(Path('/sys/class/hidraw')/node) for node in sorted(nodes)
           if (Path('/sys/class/hidraw')/node).exists()]
    refresh_paths(paths)


def refresh_paths(paths):
    subprocess.run(['udevadm','control','--reload-rules'],check=True,timeout=10)
    if paths:
        subprocess.run(['udevadm','trigger','--action=change',*paths],check=True,timeout=15)
    subprocess.run(['udevadm','settle','--timeout=15'],check=True,timeout=20)


def atomic_json(path,data,mode=0o600):
    fd,name=tempfile.mkstemp(prefix='.pending-',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


class SourceReservation:
    """Journal the runtime rule; retain recovery data until udev acknowledges it."""
    def __init__(self, guard, refresh=refresh_sources):
        self.guard=guard
        self.path=guard.rules/SOURCE_RULE_NAME
        self.journal=guard.state/'source-reservation.json'
        self.refresh=refresh
        self.record=None
        if self.journal.exists() or self.journal.is_symlink():
            with guard.open_trusted(self.journal,private=True) as stream:
                self.record=json.load(stream)
            if (not isinstance(self.record,dict) or self.record.get('version')!=1 or
                    not isinstance(self.record.get('fingerprint'),(list,type(None)))):
                raise ValueError('Invalid source reservation journal')

    def owned(self):
        with self.guard.open_trusted(self.path) as stream:
            info=os.fstat(stream.fileno())
            fingerprint=[info.st_dev,info.st_ino]
            if (not self.record or stream.read(len(SOURCE_RULE)+1)!=SOURCE_RULE or
                    self.record['fingerprint'] not in (None,fingerprint)):
                raise ValueError(f'Preserving changed source reservation: {self.path}')
            return fingerprint

    def install(self):
        if self.path.exists() or self.path.is_symlink():
            fingerprint=self.owned()
        else:
            # Record intent before linking a complete file into udev's rules.
            self.record={'version':1,'fingerprint':None}
            atomic_json(self.journal,self.record)
            fd,name=tempfile.mkstemp(prefix='.hstn-sources-',dir=self.guard.rules)
            try:
                with os.fdopen(fd,'w') as stream:
                    os.fchmod(stream.fileno(),0o644)
                    stream.write(SOURCE_RULE);stream.flush();os.fsync(stream.fileno())
                os.link(name,self.path)  # Refuse a concurrent writer, never overwrite.
            finally:Path(name).unlink(missing_ok=True)
            fingerprint=self.owned()
        self.record={'version':1,'fingerprint':fingerprint}
        atomic_json(self.journal,self.record)
        # Also refresh on recovery: a previous reload/trigger may have failed.
        self.refresh()

    def restore(self):
        if not self.record:return
        if self.path.exists() or self.path.is_symlink():
            self.owned()
            self.path.unlink()
        self.refresh()
        self.journal.unlink()
        self.record=None


class RuleGuard:
    def __init__(self,rules=RULES,state=RUNTIME,*,physical=physical_node,
                 refresh=refresh_nodes,owner_uid=0):
        self.rules=Path(rules);self.state=Path(state);self.physical=physical
        self.refresh=refresh;self.owner_uid=owner_uid
        for directory in (self.rules,self.state):
            directory.mkdir(mode=0o755,parents=True,exist_ok=True)
            info=directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=owner_uid or info.st_mode & 0o022:
                raise ValueError(f'Unsafe guard directory: {directory}')
        self.journal=self.state/'backups.json';self.saved={}
        if self.journal.exists():
            with self.open_trusted(self.journal,private=True) as stream:
                self.saved=json.load(stream)
            for name,entry in self.saved.items():
                match=RULE_NAME.fullmatch(name)
                if (not match or entry['node']!=match[2] or
                    correct_rule(entry['original'],match[2])!=entry['corrected']):
                    raise ValueError('Invalid input guard backup journal')
        self.recovery_refresh=bool(self.saved)

    def open_trusted(self,path,private=False):
        fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=self.owner_uid or
                info.st_mode & (0o077 if private else 0o022)):
                raise ValueError(f'Unsafe generated input rule or journal: {path}')
            return os.fdopen(fd,'r+')
        except BaseException:
            os.close(fd);raise

    def save(self):atomic_json(self.journal,self.saved)

    def scan_once(self):
        changed=set();present=set()
        for path in sorted(self.rules.glob('*-inputplumber-hide-hidraw*-*.rules')):
            match=RULE_NAME.fullmatch(path.name)
            if not match:continue
            present.add(path.name);node=match[2]
            if not self.physical(node):continue
            try:
                with self.open_trusted(path) as stream:
                    info=os.fstat(stream.fileno());fingerprint=[info.st_dev,info.st_ino]
                    text=stream.read(65537)
                    if len(text)>65536:raise ValueError(f'Oversized generated input rule: {path}')
                    prior=self.saved.get(path.name)
                    if prior and (prior['fingerprint']!=fingerprint or text!=prior['corrected']):
                        del self.saved[path.name];self.save()
                    corrected=correct_rule(text,node)
                    if corrected==text:continue
                    self.saved[path.name]={'original':text,'corrected':corrected,
                                           'node':node,'fingerprint':fingerprint}
                    self.save()  # Journal first: retain rollback across crashes/restarts.
                    stream.seek(0)
                    current=path.stat()
                    if ([current.st_dev,current.st_ino]!=fingerprint or stream.read()!=text):
                        del self.saved[path.name];self.save();continue
                    stream.seek(0);stream.write(corrected);stream.truncate();stream.flush();os.fsync(stream.fileno())
                    changed.add(node)
                    print(f'Corrected {path.name}',flush=True)
            except FileNotFoundError:continue  # InputPlumber removed it during teardown.
        expired=set(self.saved)-present
        if expired:
            for name in expired:del self.saved[name]
            self.save()
        recovered={entry['node'] for entry in self.saved.values()
                   if self.recovery_refresh and self.physical(entry['node'])}
        if changed or recovered:self.refresh(changed|recovered)
        self.recovery_refresh=False
        if recovered:print('Reapplied retained input rule corrections after restart.',flush=True)
        return changed

    def restore(self):
        changed=set()
        for name,entry in list(self.saved.items()):
            try:
                with self.open_trusted(self.rules/name) as stream:
                    info=os.fstat(stream.fileno())
                    if [info.st_dev,info.st_ino]!=entry['fingerprint'] or stream.read()!=entry['corrected']:
                        continue
                    stream.seek(0);stream.write(entry['original']);stream.truncate();stream.flush();os.fsync(stream.fileno())
                    changed.add(entry['node'])
            except FileNotFoundError:pass
            except (OSError,ValueError) as error:print(f'Rule restore skipped: {error}',flush=True)
        self.saved.clear();self.save()
        if changed:self.refresh(changed)


def notify(message):
    address=os.environ.get('NOTIFY_SOCKET')
    if not address:return
    if address.startswith('@'):address='\0'+address[1:]
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sock:
            sock.connect(address);sock.sendall(message.encode())
        return True
    except OSError as error:
        print(f'Systemd notification failed: {error}',flush=True);return False


def legacy_active():
    path=Path('/run/session-switch-input-diagnostic.active')
    try:
        pid=int(path.read_text().strip())
        if path.stat().st_uid!=0 or pid<=1:return False
        os.kill(pid,0);return True
    except (OSError,ValueError):return False


def main():
    if os.geteuid()!=0:raise SystemExit('This helper must run as the system session-switch-input-guard service.')
    os.umask(0o077)
    RUNTIME.mkdir(mode=0o755,parents=True,exist_ok=True)
    info=RUNTIME.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
        raise SystemExit('Unsafe input guard runtime directory')
    RUNTIME.chmod(0o755)
    lock_fd=os.open(RUNTIME/'lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if legacy_active():raise SystemExit('Stop session-switch-input-diagnostic.service before starting the permanent guard.')
    guard=RuleGuard();reservation=SourceReservation(guard);running=True;active=RUNTIME/'active'
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        reservation.install()
        guard.scan_once()
        ticks=int(Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19])
        atomic_json(active,{'version':1,'kind':'session-switch-input-guard','pid':os.getpid(),'start_ticks':ticks},0o644)
        if notify('READY=1\nSTATUS=Watching InputPlumber runtime HID rules') is False:
            raise RuntimeError('Could not notify systemd that input guard is ready')
        print('Input guard ready; watching across sessions.',flush=True)
        while running:
            reservation.owned()
            guard.scan_once();time.sleep(.5)
    finally:
        notify('STOPPING=1')
        active.unlink(missing_ok=True)
        try:
            if not running:
                try:guard.restore()
                finally:reservation.restore()
                print('Input guard stopped; surviving owned rule changes restored.',flush=True)
            else:
                print('Input guard failed; corrected rules and journal retained for restart.',flush=True)
        finally:os.close(lock_fd)


if __name__=='__main__':main()
