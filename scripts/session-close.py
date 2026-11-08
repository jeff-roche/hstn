#!/usr/bin/env python3
"""HSTN: prepare an explicit close plan, then execute it once after confirmation."""
import argparse
import ctypes
import ctypes.util
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time

TARGETS = ('steam', 'heroic', 'desktop')
RELATED = {'upc.exe', 'ubisoftconnect.exe', 'ubisoftgamelauncher.exe',
           'uplaywebcore.exe', 'ubisoftconnectwebcore.exe'}
PROTECTED = {'steam', 'steam.exe', 'steamwebhelper', 'heroic', 'gamescope',
             'wineserver', 'wineserver64', 'services.exe', 'winedevice.exe',
             'rpcss.exe', 'plugplay.exe', 'explorer.exe', 'svchost.exe'}


def normalize_prefix(value):
    if not value:
        return ''
    path = Path(value).expanduser().resolve()
    return str(path.parent if path.name == 'pfx' else path)


def process_record(path):
    if path.stat().st_uid != os.getuid():
        return None
    fields = (path/'stat').read_text().rsplit(') ',1)[1].split()
    if fields[0] in ('Z','X'):
        return None
    env = dict(item.split(b'=',1) for item in (path/'environ').read_bytes().split(b'\0') if b'=' in item)
    name = (path/'comm').read_text().strip()
    args = (path/'cmdline').read_bytes().split(b'\0')
    executable = args[0].decode(errors='replace').replace('\\','/').rsplit('/',1)[-1] if args else ''
    if executable.lower().endswith('.exe'):
        name = executable
    namespaces = [int(path.name)]
    for line in (path/'status').read_text().splitlines():
        if line.startswith('NSpid:'):
            namespaces = [int(n) for n in line.split()[1:]]
    def value(key):return env.get(key.encode(),b'').decode(errors='replace')
    return {'pid':int(path.name),'uid':os.getuid(),'start':int(fields[19]),'name':name,
            'heroic_id':value('HEROIC_APP_NAME'),'steam_id':value('SteamAppId'),
            'prefix':normalize_prefix(value('WINEPREFIX') or value('STEAM_COMPAT_DATA_PATH')),
            'namespace_pids':namespaces}


def inspect_processes(proc=Path('/proc')):
    records, errors = [], []
    for path in sorted(proc.glob('[0-9]*'),key=lambda p:int(p.name)):
        try:
            record = process_record(path)
            if record and record['pid'] != os.getpid():records.append(record)
        except (FileNotFoundError,ProcessLookupError):pass
        except (OSError,ValueError,IndexError) as error:
            errors.append(f'Cannot inspect PID {path.name}: {getattr(error,"strerror",None) or type(error).__name__}')
    return records, errors


def catalog():
    root = Path.home()/'.var/app/com.heroicgameslauncher.hgl/config/heroic'
    titles, prefixes = {}, set()
    for path in (root/'legendaryConfig/legendary/metadata').glob('*.json'):
        try:
            data=json.loads(path.read_text())
            titles[('heroic',data.get('app_name',path.stem))]=data.get('app_title') or data.get('metadata',{}).get('title') or path.stem
        except (OSError,ValueError):pass
    for path in (root/'GamesConfig').glob('*.json'):
        try:
            data=json.loads(path.read_text()).get(path.stem,{})
            prefix=normalize_prefix(data.get('winePrefix',''))
            if prefix:prefixes.add(prefix)
        except (OSError,ValueError,TypeError):pass
    try:
        games=json.loads((root/'sideload_apps/library.json').read_text()).get('games',[])
        for game in games:titles[('heroic',game['app_name'])]=game.get('title',game['app_name'])
    except (OSError,ValueError,KeyError):pass
    steam=Path.home()/'.local/share/Steam/steamapps'
    libraries={steam}
    try:
        for value in re.findall(r'"path"\s+"([^"]+)"',(steam/'libraryfolders.vdf').read_text()):
            libraries.add(Path(value.replace('\\\\','\\'))/'steamapps')
    except OSError:pass
    for library in libraries:
        for path in library.glob('appmanifest_*.acf'):
            try:
                name=re.search(r'"name"\s+"([^"]+)"',path.read_text())
                if name:titles[('steam',path.stem.removeprefix('appmanifest_'))]=name[1]
            except OSError:pass
    try:
        spec=importlib.util.spec_from_file_location('launcher_titles',Path(__file__).resolve().with_name('configure-launchers.py'))
        config=importlib.util.module_from_spec(spec);spec.loader.exec_module(config)
        shortcuts=config.read_vdf((config.detect_config('steam')/'shortcuts.vdf').read_bytes())['shortcuts']
        for game in shortcuts.values():
            if game.get('AppName'):
                titles[('steam',str(int(game['appid']) & 0xffffffff))]=game['AppName']
    except (OSError,ValueError,KeyError):pass
    return titles,prefixes


def build_plan(target, records, titles, known_prefixes, steam_switchers, heroic_switchers):
    if target not in TARGETS:raise ValueError('Unknown session target')
    apps={}
    for record in records:
        if record['uid'] != os.getuid():continue
        name=record['name'].lower()
        if name in PROTECTED:continue
        heroic=record.get('heroic_id','');steam=record.get('steam_id','')
        game=None
        if heroic and heroic not in heroic_switchers:game=('heroic',heroic)
        elif not heroic and steam.isdecimal() and int(steam)>0 and str(int(steam)) not in steam_switchers:
            game=('steam',str(int(steam)))
        if name in RELATED and (game or record.get('prefix') in known_prefixes):
            key=('related','ubisoft');label='Ubisoft Connect'
        elif game:
            key=game;label=titles.get(game,f'{game[0].title()} game {game[1]}')
        else:continue
        app=apps.setdefault(key,{'key':list(key),'label':label,'processes':[]})
        app['processes'].append(dict(record))
    return {'version':1,'target':target,'uid':os.getuid(),'created':time.time(),
            'apps':list(apps.values()),'warnings':[]}


def identity_set(plan):
    return {(p['uid'],p['pid'],p['start'],tuple(app['key']),p['name'])
            for app in plan['apps'] for p in app['processes']}


def plan_covers(approved, current):
    return approved['target']==current['target'] and identity_set(current).issubset(identity_set(approved))


def current_plan(target):
    spec=importlib.util.spec_from_file_location('activity',Path(__file__).resolve().with_name('game-activity.py'))
    activity=importlib.util.module_from_spec(spec);spec.loader.exec_module(activity)
    steam,heroic,errors=activity.switcher_ids()
    records,gaps=inspect_processes();titles,prefixes=catalog()
    plan=build_plan(target,records,titles,prefixes,steam,heroic)
    plan['warnings']=errors+gaps
    return plan


def store_plan(plan):
    directory=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'session-switch-confirmations'
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    if directory.stat().st_uid!=os.getuid() or directory.is_symlink():raise ValueError('Unsafe confirmation directory')
    directory.chmod(0o700)
    fd,name=tempfile.mkstemp(prefix='close-',suffix='.json',dir=directory)
    with os.fdopen(fd,'w') as stream:json.dump(plan,stream)
    return name


def consume_plan(path):
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
            raise ValueError('Unsafe confirmation file')
        # Removing it before use prevents reuse, including after a failed close.
        path.unlink()
        with os.fdopen(fd,'r') as stream:
            fd=None;plan=json.load(stream)
    finally:
        if fd is not None:os.close(fd)
    if (plan.get('version')!=1 or plan.get('uid')!=os.getuid() or plan.get('target') not in TARGETS
            or not 0<=time.time()-plan.get('created',0)<=300):
        raise ValueError('Confirmation expired or invalid; review the running apps again')
    return plan


def alive(fd):
    poll=select.poll();poll.register(fd,select.POLLIN)
    return not poll.poll(0)


def window_owners(windows):
    """XRes peer PIDs in our host Gamescope Xserver, never _NET_WM_PID aliases."""
    class Client(ctypes.Structure):
        _fields_=[('resource_base',ctypes.c_ulong),('resource_mask',ctypes.c_ulong)]
    class Spec(ctypes.Structure):
        _fields_=[('client',ctypes.c_ulong),('mask',ctypes.c_uint)]
    class Value(ctypes.Structure):
        _fields_=[('spec',Spec),('length',ctypes.c_long),('value',ctypes.c_void_p)]
    x11_name=ctypes.util.find_library('X11');xres_name=ctypes.util.find_library('XRes')
    if not x11_name or not xres_name:return {}
    x11=ctypes.CDLL(x11_name);res=ctypes.CDLL(xres_name)
    x11.XOpenDisplay.argtypes=[ctypes.c_char_p];x11.XOpenDisplay.restype=ctypes.c_void_p
    x11.XCloseDisplay.argtypes=[ctypes.c_void_p];x11.XFree.argtypes=[ctypes.c_void_p]
    res.XResQueryClients.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.POINTER(Client))]
    res.XResQueryClientIds.argtypes=[ctypes.c_void_p,ctypes.c_long,ctypes.POINTER(Spec),ctypes.POINTER(ctypes.c_long),ctypes.POINTER(ctypes.POINTER(Value))]
    res.XResGetClientPid.argtypes=[ctypes.POINTER(Value)];res.XResGetClientPid.restype=ctypes.c_int
    res.XResClientIdsDestroy.argtypes=[ctypes.c_long,ctypes.POINTER(Value)]
    res.XResQueryVersion.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_int)]
    display=x11.XOpenDisplay(None)
    if not display:return {}
    clients=ctypes.POINTER(Client)();values=ctypes.POINTER(Value)();count=ctypes.c_int();nvalues=ctypes.c_long()
    try:
        major=ctypes.c_int();minor=ctypes.c_int()
        if not res.XResQueryVersion(display,ctypes.byref(major),ctypes.byref(minor)) or (major.value,minor.value)<(1,2):return {}
        if not res.XResQueryClients(display,ctypes.byref(count),ctypes.byref(clients)):return {}
        specs=(Spec*count.value)(*(Spec(clients[i].resource_base,2) for i in range(count.value)))
        # Unlike QueryClients, the 1.2 API returns X11 Success (zero).
        if res.XResQueryClientIds(display,count.value,specs,ctypes.byref(nvalues),ctypes.byref(values)) != 0:return {}
        pids={values[i].spec.client:res.XResGetClientPid(ctypes.byref(values[i])) for i in range(nvalues.value)}
        owners={}
        for window in windows:
            for i in range(count.value):
                client=clients[i]
                if window & ~client.resource_mask == client.resource_base:
                    pid=pids.get(client.resource_base,-1)
                    if pid>0:owners[window]=pid
                    break
        return owners
    finally:
        if values:res.XResClientIdsDestroy(nvalues.value,values)
        if clients:x11.XFree(clients)
        x11.XCloseDisplay(display)


def request_window_close(records):
    """WM_DELETE_WINDOW only; no window destruction or global Wine shutdown."""
    if not os.environ.get('DISPLAY'):return
    try:
        tree=subprocess.run(['xwininfo','-root','-tree'],capture_output=True,text=True,timeout=2,check=True).stdout
        ids=re.findall(r'^\s*(0x[0-9a-fA-F]+)\s',tree,re.M)
        approved={record['pid']:record for record in records}
        ids=list(dict.fromkeys(ids))[:80]
        owners=window_owners([int(wid,16) for wid in ids])
        for wid in ids:
            pid=owners.get(int(wid,16))
            if pid not in approved:continue
            record=approved[pid]
            live=process_record(Path('/proc')/str(pid))
            if not live or (live['uid'],live['start'],live['name'])!=(record['uid'],record['start'],record['name']):continue
            props=subprocess.run(['xprop','-id',wid,'WM_CLASS','STEAM_OVERLAY','WM_PROTOCOLS'],capture_output=True,text=True,timeout=2).stdout
            if 'WM_DELETE_WINDOW' not in props:continue
            if re.search('heroic|steamwebhelper|session-overlay|gamescope',props,re.I) or re.search(r'STEAM_OVERLAY.*=\s*1',props):continue
            send_delete(int(wid,16))
    except (OSError,subprocess.SubprocessError):pass


def send_delete(window):
    class Data(ctypes.Union):_fields_=[('bytes',ctypes.c_char*20),('longs',ctypes.c_long*5)]
    class Client(ctypes.Structure):
        _fields_=[('type',ctypes.c_int),('serial',ctypes.c_ulong),('sent',ctypes.c_int),
                  ('display',ctypes.c_void_p),('window',ctypes.c_ulong),('message',ctypes.c_ulong),
                  ('format',ctypes.c_int),('data',Data)]
    class Event(ctypes.Union):_fields_=[('client',Client),('pad',ctypes.c_long*24)]
    lib=ctypes.CDLL(ctypes.util.find_library('X11'))
    lib.XOpenDisplay.argtypes=[ctypes.c_char_p];lib.XOpenDisplay.restype=ctypes.c_void_p
    lib.XInternAtom.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int];lib.XInternAtom.restype=ctypes.c_ulong
    lib.XSendEvent.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_long,ctypes.POINTER(Event)]
    lib.XFlush.argtypes=[ctypes.c_void_p];lib.XCloseDisplay.argtypes=[ctypes.c_void_p]
    callback_type=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p)
    ignore_error=callback_type(lambda *_:0)
    lib.XSetErrorHandler.argtypes=[ctypes.c_void_p];lib.XSetErrorHandler.restype=ctypes.c_void_p
    previous=lib.XSetErrorHandler(ctypes.cast(ignore_error,ctypes.c_void_p))
    display=lib.XOpenDisplay(None)
    if not display:
        lib.XSetErrorHandler(previous);return
    try:
        event=Event();event.client.type=33;event.client.sent=1;event.client.display=display
        event.client.window=window;event.client.message=lib.XInternAtom(display,b'WM_PROTOCOLS',0);event.client.format=32
        event.client.data.longs[0]=lib.XInternAtom(display,b'WM_DELETE_WINDOW',0)
        lib.XSendEvent(display,window,0,0,ctypes.byref(event));lib.XFlush(display)
    finally:
        lib.XCloseDisplay(display);lib.XSetErrorHandler(previous)


def execute_plan(plan, inspect=current_plan, switch=None, grace=5, term_wait=10):
    if plan['uid']!=os.getuid() or not 0<=time.time()-plan['created']<=300:
        raise ValueError('Confirmation expired; review running apps again')
    current=inspect(plan['target'])
    if not plan_covers(plan,current):
        print('Running apps changed. Review the list again before closing anything.');return 24
    approved={(p['pid'],p['start']):p for a in current['apps'] for p in a['processes']}
    handles=[]
    try:
        # Bind every PID before sending anything. Start-time checks plus pidfds
        # prevent sending a signal to a recycled PID.
        for record in approved.values():
            try:
                fd=os.pidfd_open(record['pid']);handles.append((fd,record))
                live=process_record(Path('/proc')/str(record['pid']))
                if not live or (live['uid'],live['start'],live['name'])!=(record['uid'],record['start'],record['name']):
                    if alive(fd):raise ValueError('Process identity changed; review apps again')
            except (ProcessLookupError,FileNotFoundError):continue
        print('Closing: '+', '.join(a['label'] for a in current['apps']),flush=True)
        request_window_close([record for fd,record in handles if alive(fd)])
        deadline=time.monotonic()+grace
        while any(alive(fd) for fd,_ in handles) and time.monotonic()<deadline:time.sleep(.1)
        for fd,record in handles:
            if alive(fd):
                try:signal.pidfd_send_signal(fd,signal.SIGTERM)
                except ProcessLookupError:pass
        deadline=time.monotonic()+term_wait
        while any(alive(fd) for fd,_ in handles) and time.monotonic()<deadline:time.sleep(.1)
        remaining=inspect(plan['target'])
        if any(alive(fd) for fd,_ in handles) or remaining['apps']:
            labels=', '.join(a['label'] for a in remaining['apps']) or 'a confirmed process'
            print('Still running: '+labels+'. Close it manually before switching.');return 20
        if switch is None:
            helper=Path.home()/'.local/bin/session-switch'
            os.execv(str(helper),[str(helper),plan['target']])
        return switch(plan['target'])
    finally:
        for fd,_ in handles:os.close(fd)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('plan');prepare.add_argument('target',choices=TARGETS)
    execute=commands.add_parser('execute');execute.add_argument('path')
    args=parser.parse_args()
    try:
        if args.command=='plan':
            plan=current_plan(args.target)
            plan['path']=store_plan(plan) if plan['apps'] else None
            print(json.dumps(plan));return 0
        return execute_plan(consume_plan(args.path))
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(f'Close and switch failed: {error}',file=sys.stderr);return 21


if __name__=='__main__':sys.exit(main())
