"""Read protocol capabilities from an isolated installed OpenCode server; no model or prompts."""
import base64
import json
import os
from pathlib import Path
import socket
import sys
import threading
import subprocess
import tempfile
import time
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine
from guardian.server import Server
exe=Path(os.environ['APPDATA'])/'npm/node_modules/opencode-ai/bin/opencode.exe'
with tempfile.TemporaryDirectory(prefix='guardian-navigation-',ignore_cleanup_errors=True) as tmp:
    root=Path(tmp)
    engine=Engine(':memory:')
    guard=Server(('127.0.0.1',0),engine,'fixture-admin',adapter_token='fixture-adapter')
    guard_thread=threading.Thread(target=guard.serve_forever,daemon=True);guard_thread.start()
    (root/'token').write_text('fixture-adapter')
    probe=root/'probe.mjs'
    probe.write_text('import Guardian from '+json.dumps((ROOT/'integrations/opencode/guardian.mjs').as_uri())+'; import {writeFileSync} from "node:fs"; export default async context=>{writeFileSync('+json.dumps(str(root/'capabilities.json'))+',JSON.stringify({hasPublish:typeof context.client?.tui?.publish==="function",hasSelectSession:typeof context.client?.tui?.selectSession==="function",hasServerUrl:!!context.serverUrl}));return await Guardian(context);};')
    config={'autoupdate':False,'share':'disabled','plugin':[probe.as_uri()],'enabled_providers':[]}
    (root/'opencode.json').write_text(json.dumps(config))
    env={**os.environ,'GUARDIAN_MODE':'observe','GUARDIAN_TOKEN_FILE':str(root/'token'),'GUARDIAN_PORT':str(guard.server_port),'XDG_CONFIG_HOME':str(root/'config'),'XDG_DATA_HOME':str(root/'data'),'XDG_STATE_HOME':str(root/'state'),
      'OPENCODE_CONFIG':str(root/'opencode.json'),'OPENCODE_DISABLE_AUTOUPDATE':'true','OPENCODE_DISABLE_MODELS_FETCH':'true',
      'OPENCODE_DISABLE_DEFAULT_PLUGINS':'true','OPENCODE_SERVER_PASSWORD':'fixture-only-password'}
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    auth='Basic '+base64.b64encode(b'opencode:fixture-only-password').decode()
    def request(path,body=None,timeout=4):
        req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,json.dumps(body).encode() if body is not None else None,{'Authorization':auth,'Content-Type':'application/json'})
        with opener.open(req,timeout=timeout) as response:return json.load(response)
    with (root/'server.log').open('w') as log:
        process=subprocess.Popen([str(exe),'serve','--hostname','127.0.0.1','--port',str(port),'--print-logs'],cwd=root,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+40
            while True:
                try:health=request('/global/health');break
                except (OSError,ValueError):
                    if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Fixture server failed to start')
                    time.sleep(.2)
            spec=request('/doc')
            session=request('/session',{},timeout=120)
            report={'version':health.get('version'),'paths':[p for p in spec['paths'] if p.startswith('/tui/')],
                    'plugin':json.loads((root/'capabilities.json').read_text()) if (root/'capabilities.json').exists() else None}
            for path,body in [('/tui/select-session',{'sessionID':session['id']}),('/tui/publish',{'type':'tui.session.select','properties':{'sessionID':session['id']}})]:
                try:report[path]={'accepted':request(path,body)}
                except urllib.error.HTTPError as error:report[path]={'http_status':error.code}
            deadline=time.monotonic()+6
            while not guard.connections.snapshot() and time.monotonic()<deadline:time.sleep(.1)
            instances=guard.connections.snapshot()
            if not instances:raise RuntimeError('Guardian plugin did not register')
            def guardian_request(path,body,admin=False):
                req=urllib.request.Request(guard.origin+path,json.dumps(body).encode(),{'Authorization':'Bearer '+('fixture-admin' if admin else 'fixture-adapter'),'Content-Type':'application/json'})
                with opener.open(req,timeout=4) as response:return json.load(response)
            event=guardian_request('/api/opencode/check',{'instance_id':instances[0]['instance_id'],'mode':'observe','payload':{'session_id':session['id'],'tool_use_id':'fixture-navigation','tool_name':'Read','tool_input':{'file_path':'fixture.txt'}}})
            queued=guardian_request('/api/source/open',{'event_id':event['event_id']},True)
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                status=guard.navigation.status(event['event_id'])
                if status and status['state'] in ('dispatched','failed','expired'):break
                time.sleep(.1)
            report['guardian_bridge']={'initial_state':queued.get('state'),'final_state':status.get('state') if status else None,'visible_session_verified':False,'model_requests_sent':0}
            (ROOT/'.local/opencode-navigation-probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report))
            if report['guardian_bridge']['final_state']!='dispatched':raise RuntimeError('Navigation bridge was not accepted')
        except Exception as error:
            (ROOT/'.local/opencode-navigation-probe-failure.json').write_text(json.dumps({'status':'failed','error_type':type(error).__name__,'model_requests_sent':0}),encoding='utf-8')
            raise
        finally:
            process.terminate();process.wait(timeout=10)
            guard.shutdown();guard.server_close();guard_thread.join();engine.close()
            log.flush()
            (ROOT/'.local/opencode-navigation-probe.log').write_text((root/'server.log').read_text(errors='replace').replace(str(root),'<fixture>'),encoding='utf-8')
