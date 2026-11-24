"""Best-effort ancestor terminal activation. No titles, command lines or keystrokes."""
import os
import ntpath
import json
from pathlib import Path
import subprocess
import sys
import time

TERMINALS={'windowsterminal.exe','openconsole.exe','conhost.exe'}
CONSOLE_CLIENTS={'python.exe','pythonw.exe','node.exe','bun.exe','claude.exe','opencode.exe','codex.exe','powershell.exe','pwsh.exe','cmd.exe'}

class SourceWindows:
    def __init__(self,api=None):
        self.api=api
        if api is None and os.name=='nt':
            try:self.api=Win32()
            except (OSError,AttributeError):pass

    def terminal(self,process,hwnd,console=False):
        if not process:return False
        if process['name'] in TERMINALS:return True
        return bool(console and process['name'] in CONSOLE_CLIENTS and hasattr(self.api,'class_name')
                    and self.api.class_name(hwnd)=='ConsoleWindowClass')

    def capture(self,pid,source_names=('python.exe','pythonw.exe')):
        if self.api is None or type(pid) is not int or not 0<pid<2**32:return None
        try:
            seen=set();child_created=None;candidates=[];source=None
            for depth in range(10):
                if pid in seen:break
                seen.add(pid);process=self.api.process(pid)
                if not process or child_created is not None and process['created']>child_created:break
                if depth==0 and process['name'] not in source_names:return None
                if depth==0:source=process
                if process['name'] in TERMINALS:candidates.append(process)
                child_created=process['created'];pid=process['parent']
                if not pid:break
            windows=self.api.windows()
            matches=[{'pid':p['pid'],'created':p['created'],'hwnd':hwnd} for p in candidates for hwnd,owner in windows if owner==p['pid']]
            if len(matches)==1:return matches[0]
            if source and hasattr(self.api,'source_console'):
                console=self.api.source_console(source['pid'])
                current=self.api.process(source['pid'])
                if not console or not current or current['created']!=source['created']:return None
                linked=self.api.console_target(console)
                if not linked:return None
                hwnd,console_pid=linked
                owner=next((owner for window,owner in windows if window==hwnd),None)
                terminal=self.api.process(owner) if owner else None
                host=self.api.process(console_pid)
                if self.terminal(terminal,hwnd,True) and self.terminal(host,console,True):
                    return {'pid':terminal['pid'],'created':terminal['created'],'hwnd':hwnd,
                            'console_hwnd':console,'console_pid':console_pid,'console_created':host['created']}
            return None
        except (OSError,ValueError,OverflowError):return None

    def activate(self,target):
        if not target or self.api is None:return {'window_foreground_verified':False,'window_reason':'unavailable'}
        try:
            process=self.api.process(target['pid'])
            matches=[hwnd for hwnd,owner in self.api.windows() if owner==target['pid']]
            precise='console_hwnd' in target
            if not process or process['created']!=target['created'] or not self.terminal(process,target['hwnd'],precise) or (target['hwnd'] not in matches if precise else matches!=[target['hwnd']]):
                return {'window_foreground_verified':False,'window_reason':'closed_or_ambiguous'}
            if precise:
                host=self.api.process(target['console_pid'])
                if not host or host['created']!=target['console_created'] or not self.terminal(host,target['console_hwnd'],True) or self.api.console_target(target['console_hwnd'])!=(target['hwnd'],target['console_pid']):
                    return {'window_foreground_verified':False,'window_reason':'console_binding_changed'}
            self.api.activate(target['hwnd'])
            verified=self.api.foreground()==target['hwnd']
            return {'window_foreground_verified':verified,'window_reason':'foreground' if verified else 'os_not_confirmed'}
        except (OSError,ValueError,OverflowError):return {'window_foreground_verified':False,'window_reason':'unavailable'}

class Win32:
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c,self.w=c,w
        self.kernel=c.WinDLL('kernel32',use_last_error=True)
        self.user=c.WinDLL('user32',use_last_error=True)
        self.nt=c.WinDLL('ntdll',use_last_error=True)
        class Basic(c.Structure):
            _fields_=[('exit',c.c_long),('peb',c.c_void_p),('affinity',c.c_size_t),('priority',c.c_long),('pid',c.c_size_t),('parent',c.c_size_t)]
        self.Basic=Basic
        self.callback=c.WINFUNCTYPE(w.BOOL,w.HWND,c.c_ssize_t)
        self.kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.kernel.OpenProcess.restype=w.HANDLE
        self.kernel.CloseHandle.argtypes=[w.HANDLE]
        self.kernel.GetProcessTimes.argtypes=[w.HANDLE]+[c.POINTER(w.FILETIME)]*4
        self.kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
        self.nt.NtQueryInformationProcess.argtypes=[w.HANDLE,w.ULONG,c.c_void_p,w.ULONG,c.POINTER(w.ULONG)];self.nt.NtQueryInformationProcess.restype=c.c_long
        self.user.EnumWindows.argtypes=[self.callback,c.c_ssize_t]
        self.user.IsWindowVisible.argtypes=[w.HWND]
        self.user.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
        self.user.ShowWindowAsync.argtypes=[w.HWND,c.c_int]
        self.user.IsIconic.argtypes=[w.HWND]
        self.user.SetForegroundWindow.argtypes=[w.HWND]
        self.user.GetForegroundWindow.restype=w.HWND
        self.user.GetAncestor.argtypes=[w.HWND,w.UINT];self.user.GetAncestor.restype=w.HWND
        self.user.GetClassNameW.argtypes=[w.HWND,w.LPWSTR,c.c_int]

    def class_name(self,hwnd):
        name=self.c.create_unicode_buffer(256)
        return name.value if self.user.GetClassNameW(hwnd,name,len(name)) else None

    def source_console(self,pid):
        try:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('console_locator.py')),str(pid)],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                timeout=.8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
            hwnd=json.loads(result.stdout)
            return hwnd if type(hwnd) is int and 0<hwnd<2**64 else None
        except (OSError,ValueError,subprocess.SubprocessError):return None

    def console_target(self,hwnd):
        root=self.user.GetAncestor(hwnd,3)  # GA_ROOTOWNER: console -> presentation window.
        if not root or not self.user.IsWindowVisible(root):return None
        owner=self.w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd,self.c.byref(owner))
        return (int(root),owner.value) if owner.value else None

    def process(self,pid):
        c,w=self.c,self.w
        handle=self.kernel.OpenProcess(0x1000,False,pid)
        if not handle:return None
        try:
            basic=self.Basic();length=w.ULONG()
            if self.nt.NtQueryInformationProcess(handle,0,c.byref(basic),c.sizeof(basic),c.byref(length))!=0:return None
            times=[w.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(handle,*[c.byref(t) for t in times]):return None
            name=c.create_unicode_buffer(32768);size=w.DWORD(len(name))
            if not self.kernel.QueryFullProcessImageNameW(handle,0,name,c.byref(size)):return None
            return {'pid':pid,'parent':int(basic.parent),'created':(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime,'name':ntpath.basename(name.value).lower()}
        finally:self.kernel.CloseHandle(handle)

    def windows(self):
        result=[];count=0
        @self.callback
        def visit(hwnd,param):
            nonlocal count
            count+=1
            if count>1024:return False
            if self.user.IsWindowVisible(hwnd):
                pid=self.w.DWORD();self.user.GetWindowThreadProcessId(hwnd,self.c.byref(pid));result.append((int(hwnd),pid.value))
            return True
        if not self.user.EnumWindows(visit,0):raise OSError('Window enumeration incomplete')
        return result

    def activate(self,hwnd):
        if self.user.IsIconic(hwnd):
            self.user.ShowWindowAsync(hwnd,9)
            deadline=time.monotonic()+.25
            while self.user.IsIconic(hwnd) and time.monotonic()<deadline:time.sleep(.01)
        self.user.SetForegroundWindow(hwnd)
        # Activation across input queues can complete after SetForegroundWindow returns.
        deadline=time.monotonic()+.25
        while self.foreground()!=hwnd and time.monotonic()<deadline:time.sleep(.01)

    def foreground(self):return self.user.GetForegroundWindow()
