"""Real Pi CLI, isolated config, local model fixture and harmless file writes.

No cloud model or real credentials. Synthetic deny/review decisions test the
execution boundary, not the accuracy of production detection rules.
"""
import argparse
import hashlib
import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine
from guardian.server import Server
import guardian.engine as engine_module
from scripts.install_pi import manage


class Model(BaseHTTPRequestHandler):
    def log_message(self,*args):pass

    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
        self.server.requests+=1
        results=[m for m in data.get('messages',[]) if m.get('role')=='tool']
        self.server.results.extend(results)
        if results:
            delta={'role':'assistant','content':'Local fixture completed.'};finish='stop'
        else:
            delta={'role':'assistant','content':None,'tool_calls':[{'index':0,'id':'call_pi_fixture','type':'function',
                'function':{'name':'write','arguments':json.dumps({'path':self.server.target,'content':'GUARDIAN_PI_FIXTURE'})}}]}
            finish='tool_calls'
        chunks=[{'id':'chatcmpl-fixture','object':'chat.completion.chunk','created':1,'model':'local-fixture',
                 'choices':[{'index':0,'delta':delta,'finish_reason':None}]},
                {'id':'chatcmpl-fixture','object':'chat.completion.chunk','created':1,'model':'local-fixture',
                 'choices':[{'index':0,'delta':{},'finish_reason':finish}]}]
        body=(''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode()
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)


def rpc_run(command, env, workspace, confirm, before_confirm=None, state_only=False):
    """Exercise Pi's real extension UI protocol, not a replacement Pi API."""
    records=queue.Queue();dialogs=0;settled=False;diagnostic='';state={}
    with tempfile.TemporaryFile() as stderr:
        process=subprocess.Popen(command+['--mode','rpc'],env=env,cwd=workspace,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr)
        def read():
            try:
                for line in process.stdout:records.put(line)
            finally:records.put(None)
        reader=threading.Thread(target=read,daemon=True);reader.start()
        def send(value):
            process.stdin.write((json.dumps(value)+'\n').encode());process.stdin.flush()
        try:
            send({'type':'get_state','id':'fixture-state'} if state_only else
                 {'type':'prompt','id':'fixture-prompt','message':'Run the single harmless fixture write offered by the local model, then finish.'})
            deadline=time.monotonic()+90
            while not settled:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Pi RPC did not settle')
                try:line=records.get(timeout=remaining)
                except queue.Empty:raise TimeoutError('Pi RPC did not settle') from None
                if line is None:raise RuntimeError('Pi RPC exited before settling')
                message=json.loads(line)
                if message.get('type')=='response' and message.get('success') is False:
                    raise RuntimeError('Pi RPC command failed')
                if state_only and message.get('type')=='response' and message.get('id')=='fixture-state':
                    state=message.get('data',{});settled=True;continue
                if message.get('type')=='extension_ui_request' and message.get('method')=='confirm':
                    dialogs+=1
                    if dialogs!=1 or message.get('title')!='Guardian: allow this action once?':
                        raise RuntimeError('Unexpected confirmation dialog')
                    if not 0<message.get('timeout',0)<=300000:raise RuntimeError('Missing bounded confirmation timeout')
                    if before_confirm:before_confirm()
                    send({'type':'extension_ui_response','id':message['id'],'confirmed':confirm})
                settled=message.get('type')=='agent_settled'
        except Exception as error:
            diagnostic=type(error).__name__+': '+str(error)
        finally:
            process.stdin.close()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
            reader.join(timeout=5);process.stdout.close()
        stderr.seek(0);diagnostic+='\n'+stderr.read()[-2000:].decode('utf-8',errors='replace')
    return subprocess.CompletedProcess(command,process.returncode,json.dumps(state),diagnostic),dialogs,settled


def run(cli,output):
    if not cli.is_file():raise ValueError('Install Pi separately in an isolated directory or specify --pi-cli')
    package_file=cli.parents[2]/'package.json'
    package=json.loads(package_file.read_text(encoding='utf-8'))
    if package.get('name')!='@earendil-works/pi-coding-agent':
        raise ValueError('Expected the official Pi package dist/bundle/cli.js')
    rows=[];original=engine_module.assess
    def assess(tool,args):
        action={'denied.txt':'deny','review.txt':'review'}.get(args.get('path')) if tool=='write' else None
        if not action:return original(tool,args)
        return [dict(id='fixture_pi_gate',title='Synthetic Pi execution check',action=action,
                     reason='Harmless test file gated only in this isolated service.',impact='Only an isolated fixture file can be written.')]
    (ROOT/'.local/test-temp').mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='guardian-pi-real-',dir=ROOT/'.local/test-temp') as directory:
        root=Path(directory);agent=root/'agent';agent.mkdir();token=root/'token';token.write_text('fixture-token')
        guard=Server(('127.0.0.1',0),Engine(':memory:'),'fixture-token')
        guard.integrations=lambda force=False:[]
        model=ThreadingHTTPServer(('127.0.0.1',0),Model)
        for server in (guard,model):threading.Thread(target=server.serve_forever,daemon=True).start()
        (agent/'models.json').write_text(json.dumps({'providers':{'guardian-fixture':{
            'baseUrl':f'http://127.0.0.1:{model.server_port}/v1','api':'openai-completions','apiKey':'local-fixture',
            'models':[{'id':'local-fixture','reasoning':False,'input':['text'],'contextWindow':32768,'maxTokens':1024}]}}}))
        (agent/'settings.json').write_text(json.dumps({'defaultProvider':'guardian-fixture','defaultModel':'local-fixture',
            'cacheWarming':'off','quietStartup':True}))
        loader=agent/'extensions/guardian-agent-security.js';manage(loader,'install')
        env={k:v for k,v in os.environ.items() if k.upper() in {
            'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','USERPROFILE','APPDATA','LOCALAPPDATA'}}
        env.update(PI_CODING_AGENT_DIR=str(agent),PI_CODING_AGENT_SESSION_DIR=str(root/'sessions'),PI_OFFLINE='1',
                   GUARDIAN_TOKEN_FILE=str(token),GUARDIAN_PORT=str(guard.server_port),TEMP=str(root),TMP=str(root),
                   NO_PROXY='127.0.0.1,localhost')
        try:
            with patch.object(engine_module,'assess',side_effect=assess):
                cases=[('allow','allowed.txt','protect',True,'succeeded'),('deny','denied.txt','protect',False,'blocked'),
                       ('observe','denied.txt','observe',True,'succeeded'),('review_headless','review.txt','protect',False,'blocked'),
                       ('failure','directory','protect',False,'failed'),
                       ('rpc_confirm','review.txt','protect',True,'succeeded'),
                       ('rpc_reject','review.txt','protect',False,'blocked'),
                       ('rpc_revoked','review.txt','protect',False,'blocked'),
                       ('persistent_resume','allowed.txt','protect',True,'succeeded'),
                       ('rpc_uninstalled','review.txt','protect',True,None)]
                for name,target,mode,should_exist,receipt in cases:
                    workspace=root/name;workspace.mkdir();model.target=target;model.results=[];model.requests=0
                    if name=='failure':(workspace/target).mkdir()
                    if name=='rpc_uninstalled':manage(loader,'uninstall')
                    guard.policy.set('pi-extension',mode)
                    (root/'runtime-modes.json').write_text(json.dumps({'pi-extension':mode}))
                    before={e['event_id'] for e in guard.engine.events()}
                    command=['node',str(cli),'--offline','--no-session','--no-mcp','--no-skills',
                        '--no-context-files','--no-prompt-templates','--no-themes','--no-approve',
                        '--provider','guardian-fixture','--model','local-fixture','--thinking','off','--tools','write']
                    if name=='persistent_resume':command.remove('--no-session')
                    dialogs=0;settled=True
                    if name.startswith('rpc_'):
                        result,dialogs,settled=rpc_run(command,env,workspace,name!='rpc_reject',
                            guard.engine.revoke_approvals if name=='rpc_revoked' else None)
                    else:
                        result=subprocess.run(command+['--mode','json','-p',
                            'Run the single harmless fixture write offered by the local model, then finish.'],
                            env=env,cwd=workspace,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
                    events=[e for e in guard.engine.events() if e['event_id'] not in before]
                    actual=(workspace/target).is_file()
                    row=dict(case=name,exit_code=result.returncode,model_requests=model.requests,tool_results=len(model.results),
                             file_created=actual,expected_file_created=should_exist,events=len(events),
                             states=[e.get('execution_state') for e in events],verdicts=[e.get('verdict') for e in events])
                    expected_events=0 if name=='rpc_uninstalled' else 1
                    row['passed']=result.returncode==0 and bool(model.results) and actual==should_exist and len(events)==expected_events
                    if expected_events:row['passed']=row['passed'] and events[0].get('execution_state')==receipt
                    if events:
                        locator=guard.origins.locate(events[0])
                        if name=='persistent_resume':
                            resume=locator.get('command','').removeprefix('pi --session ')
                            resumed,_,ready=rpc_run(command+['--session',resume],env,workspace,False,state_only=True)
                            state=json.loads(resumed.stdout)
                            row['resume_same_session']=ready and resumed.returncode==0 and state.get('sessionId')==resume and bool(state.get('sessionFile'))
                            row['resume_no_model_request']=model.requests==row['model_requests']
                            row['passed']=row['passed'] and row['resume_same_session'] and row['resume_no_model_request']
                        else:
                            row['no_ephemeral_resume_command']='command' not in locator
                            row['passed']=row['passed'] and row['no_ephemeral_resume_command']
                    if name.startswith('rpc_'):
                        expected={'rpc_confirm':['confirmed'],'rpc_reject':['not_confirmed'],'rpc_revoked':[None],'rpc_uninstalled':[]}[name]
                        row.update(confirmation_dialogs=dialogs,agent_settled=settled,
                            native_outcomes=[e.get('native_confirmation',{}).get('outcome') for e in events])
                        row['passed']=row['passed'] and dialogs==expected_events and settled and row['native_outcomes']==expected
                    if not row['passed']:row['diagnostic']=(result.stderr+result.stdout)[-2500:]
                    rows.append(row);print(json.dumps(row),flush=True)
                    if not row['passed']:break
        finally:
            for server in (model,guard):server.shutdown();server.server_close()
            guard.engine.close()
    report={'scope':'real Pi CLI global extension loading and file side effects; local synthetic model and decisions',
            'client':{'package':package['name'],'version':package['version']},
            'adapter_sha256':hashlib.sha256((ROOT/'integrations/pi/guardian.mjs').read_bytes()).hexdigest(),
            'passed':len(rows)==len(cases) and all(r['passed'] for r in rows),'cloud_model_used':False,'cases':rows}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--pi-cli',type=Path,default=ROOT/'.local/pi-runtime-validation/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js')
    parser.add_argument('--output',type=Path,default=ROOT/'.local/pi-real-verification.json')
    args=parser.parse_args()
    raise SystemExit(0 if run(args.pi_cli.resolve(),args.output)['passed'] else 1)
