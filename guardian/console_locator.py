"""Read a process's console association in a disposable helper.

Never reads console text, titles or input; never detaches the Guardian server.
"""
import ctypes as c
from ctypes import wintypes as w
import json
import os
import sys


def locate(pid):
    if os.name!='nt' or type(pid) is not int or not 0<pid<2**32:return None
    kernel=c.WinDLL('kernel32',use_last_error=True)
    kernel.AttachConsole.argtypes=[w.DWORD];kernel.AttachConsole.restype=w.BOOL
    kernel.GetConsoleWindow.restype=w.HWND
    kernel.GetConsoleProcessList.argtypes=[c.POINTER(w.DWORD),w.DWORD]
    kernel.GetConsoleProcessList.restype=w.DWORD
    # Only this short-lived helper changes its console attachment.
    kernel.FreeConsole()
    if not kernel.AttachConsole(pid):return None
    try:
        members=(w.DWORD*4096)()
        count=kernel.GetConsoleProcessList(members,len(members))
        if not 0<count<=len(members) or pid not in members[:count]:return None
        hwnd=kernel.GetConsoleWindow()
        return int(hwnd) if hwnd else None
    finally:kernel.FreeConsole()


if __name__=='__main__':
    try:result=locate(int(sys.argv[1]))
    except (OSError,ValueError,IndexError):result=None
    print(json.dumps(result))
