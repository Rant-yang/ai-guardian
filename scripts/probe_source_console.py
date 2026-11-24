"""Exercise only our own disposable console windows; no agent conversations."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.source_window import SourceWindows


def main():
    processes=[];report={'scope':'two synthetic Python console processes; no agent messages, titles, screen capture or keystrokes','captures':[]}
    try:
        for _ in range(2):
            startup=subprocess.STARTUPINFO()
            startup.dwFlags=subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow=7  # SW_SHOWMINNOACTIVE
            processes.append(subprocess.Popen([sys.executable,'-c','import time; time.sleep(90)'],
                creationflags=subprocess.CREATE_NEW_CONSOLE,startupinfo=startup))
        windows=SourceWindows();targets=[]
        for process in processes:
            target=None;deadline=time.monotonic()+8
            while time.monotonic()<deadline and not target:
                target=windows.capture(process.pid)
                if not target:time.sleep(.2)
            targets.append(target)
            console=windows.api.source_console(process.pid)
            linked=windows.api.console_target(console) if console else None
            row={'captured':bool(target),'console_binding':bool(target and 'console_hwnd' in target),
                 'source_process_readable':bool(windows.api.process(process.pid)),
                 'console_found':bool(console),'visible_root_found':bool(linked)}
            if linked:
                owner=next((pid for hwnd,pid in windows.api.windows() if hwnd==linked[0]),None)
                root=windows.api.process(owner) if owner else None
                host=windows.api.process(linked[1])
                row.update(root_name=root['name'] if root else None,console_host_name=host['name'] if host else None,
                           root_class=windows.api.class_name(linked[0]),console_class=windows.api.class_name(console))
            report['captures'].append(row)
        report['distinct_windows']=bool(all(targets) and targets[0]['hwnd']!=targets[1]['hwnd'])
        report['foreground_results']=[]
        if report['distinct_windows']:
            for target in reversed(targets):report['foreground_results'].append(windows.activate(target))
        report['completed']=report['distinct_windows'] and all(r['window_foreground_verified'] for r in report['foreground_results'])
    finally:
        for process in processes:
            if process.poll() is None:process.terminate()
            process.wait(timeout=5)
        report['fixture_processes_closed']=all(p.poll() is not None for p in processes)
        (ROOT/'.local/source-console-probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))


if __name__=='__main__':main()
