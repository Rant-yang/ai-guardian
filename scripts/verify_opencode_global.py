"""Check real installed OpenCode loads the user plugin from unrelated directories.

No model prompt is sent. Own temporary HTTP processes are stopped afterward.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parent.parent


def main():
    exe=Path(os.environ['APPDATA'])/'npm/node_modules/opencode-ai/bin/opencode.exe'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    token=(ROOT/'.local/admin-token').read_text().strip()
    report=[]
    for name in ('a','b'):
        folder=ROOT/'.local/global-smoke'/name
        folder.mkdir(parents=True,exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        logfile=folder/'startup.log'
        with logfile.open('w',encoding='utf-8') as log:
            process=subprocess.Popen([str(exe),'serve','--hostname','127.0.0.1','--port',str(port),'--print-logs'],
                cwd=folder,env={**os.environ,'OPENCODE_DISABLE_AUTOUPDATE':'true'},stdout=log,stderr=log)
            verified=False
            try:
                deadline=time.monotonic()+80
                while time.monotonic()<deadline and process.poll() is None:
                    try:
                        # /path initializes the workspace without a chat or model request.
                        with opener.open(f'http://127.0.0.1:{port}/path',timeout=2) as response:
                            response.read()
                    except Exception:
                        pass
                    request=urllib.request.Request('http://127.0.0.1:8765/api/connections',headers={'Authorization':'Bearer '+token})
                    with opener.open(request,timeout=3) as response:
                        rows=json.load(response)
                    hashes={hashlib.sha256(str(folder).encode()).hexdigest()[:16],
                            hashlib.sha256(folder.as_posix().encode()).hexdigest()[:16]}
                    if any(row['project_id'] in hashes and row['online'] for row in rows):
                        verified=True;break
                    time.sleep(1)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
        report.append({'directory':str(folder),'global_plugin_registered':verified,'model_requests_sent':0})
        print(json.dumps(report[-1]),flush=True)
    (ROOT/'docs/opencode-global-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if all(row['global_plugin_registered'] for row in report) else 1


if __name__=='__main__':
    raise SystemExit(main())
