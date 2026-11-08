#!/usr/bin/env python3
"""Maintain the narrow InputPlumber HID rule correction across sessions.

Installed as root-owned code under /usr/local/libexec. Never enables controller
management or changes launcher settings. The user-side preflight still verifies
physical exclusion before starting a launcher with the overlay.
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


def correct_rule(text,node):
    lines=text.splitlines(keepends=True)
    for index,line in enumerate(lines):
        if (line.startswith('ACTION=="add|change", SUBSYSTEMS=="hidraw", ')
                and f'KERNEL=="{node}",' in line and 'KERNELS==' in line):
            lines[index]=line.replace('SUBSYSTEMS=="hidraw"','SUBSYSTEM=="hidraw"',1)
    return ''.join(lines)


def physical_node(node):
    device=Path('/sys/class/hidraw')/node/'device'
    return device.exists() and '/devices/virtual/' not in str(device.resolve())


def refresh_nodes(nodes):
    subprocess.run(['udevadm','control','--reload-rules'],check=True,timeout=10)
    paths=[str(Path('/sys/class/hidraw')/node) for node in sorted(nodes)
           if (Path('/sys/class/hidraw')/node).exists()]
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
    guard=RuleGuard();running=True;active=RUNTIME/'active'
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        guard.scan_once()
        ticks=int(Path('/proc/self/stat').read_text().rsplit(') ',1)[1].split()[19])
        atomic_json(active,{'version':1,'kind':'session-switch-input-guard','pid':os.getpid(),'start_ticks':ticks},0o644)
        if notify('READY=1\nSTATUS=Watching InputPlumber runtime HID rules') is False:
            raise RuntimeError('Could not notify systemd that input guard is ready')
        print('Input guard ready; watching across sessions.',flush=True)
        while running:
            guard.scan_once();time.sleep(.5)
    finally:
        notify('STOPPING=1')
        active.unlink(missing_ok=True)
        try:
            if not running:
                guard.restore()
                print('Input guard stopped; surviving owned rule changes restored.',flush=True)
            else:
                print('Input guard failed; corrected rules and journal retained for restart.',flush=True)
        finally:os.close(lock_fd)


if __name__=='__main__':main()
