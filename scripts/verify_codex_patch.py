"""Isolated installed Codex CLI with a fixed loopback Responses fixture.

The fourth case simulates a human approval on this fixture's in-memory Engine.
It never approves an event in the running Guardian service or user's sessions.
All patches and model responses are fixed synthetic values, not cloud inference.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine, digest
from guardian.server import Server


class ResponsesFixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        body=json.dumps({'object':'list','data':[{'id':'gpt-5','object':'model'}]}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_POST(self):
        size=int(self.headers.get('Content-Length',0))
        if size>2_000_000:self.send_error(413);return
        request=json.loads(self.rfile.read(size));self.server.requests+=1
        self.server.offered_tools=sorted({tool.get('name','') for tool in request.get('tools',[])})
        outputs=[item for item in request.get('input',[]) if isinstance(item,dict) and item.get('type') in ('custom_tool_call_output','function_call_output')]
        self.server.results.extend(outputs)
        retry=getattr(self.server,'retry_approval',False)
        if retry and self.server.requests==2 and outputs:
            pending=[e for e in self.server.engine.events() if e['event_id'] not in self.server.before]
            if len(pending)==1 and pending[0]['verdict']=='review' and 'Guardian:' in json.dumps(outputs):
                self.server.engine.approve(pending[0]['event_id'],'approve')
        issue_retry=retry and self.server.requests in (2,3) and bool(outputs)
        if (outputs or self.server.requests>2) and not issue_retry:
            item={'type':'message','id':'msg_fixture','role':'assistant','status':'completed',
                  'content':[{'type':'output_text','text':'Local fixture complete.','annotations':[]}]}
        else:item={'type':'custom_tool_call','id':'ct_fixture_'+str(self.server.requests),'call_id':'call_fixture_'+str(self.server.requests),'name':'apply_patch','input':self.server.patch,'status':'completed'}
        response={'id':'resp_fixture_'+str(self.server.requests),'object':'response','created_at':1,'status':'completed','model':'gpt-5','output':[item],
                  'usage':{'input_tokens':100,'output_tokens':30,'total_tokens':130}}
        frames=[('response.created',{'response':{**response,'status':'in_progress','output':[]}}),
                ('response.output_item.added',{'output_index':0,'item':{**item,'status':'in_progress'}}),
                ('response.output_item.done',{'output_index':0,'item':item}),('response.completed',{'response':response})]
        body=''.join('event: '+name+'\ndata: '+json.dumps({'type':name,'sequence_number':i,**data})+'\n\n' for i,(name,data) in enumerate(frames)).encode()
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)


def main():
    package=Path(os.environ['APPDATA'])/'npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor'
    executables=list(package.glob('*/codex/codex.exe'))
    if len(executables)!=1:raise SystemExit('Expected one installed Codex executable')
    (ROOT/'.local/test-temp').mkdir(parents=True,exist_ok=True)
    rows=[]
    with tempfile.TemporaryDirectory(prefix='codex-patch-',dir=ROOT/'.local/test-temp',ignore_cleanup_errors=True) as directory:
        folder=Path(directory);home=folder/'home';workspace=folder/'workspace';home.mkdir();workspace.mkdir()
        env={k:v for k,v in os.environ.items() if not k.startswith(('CODEX_','OPENAI_'))}
        env.update(CODEX_HOME=str(home),GUARDIAN_FIXTURE_KEY='local-fake-key',NO_PROXY='127.0.0.1,localhost')
        process_temp=folder/'process-temp';process_temp.mkdir()
        env.update(TEMP=str(process_temp),TMP=str(process_temp))
        version=subprocess.run([str(executables[0]),'--version'],env=env,capture_output=True,text=True,timeout=10).stdout.strip()
        engine=Engine(':memory:');guard=Server(('127.0.0.1',0),engine,'fixture-token');guard.policy.set('codex-hook','protect');guard.integrations=lambda force=False:[]
        model=ThreadingHTTPServer(('127.0.0.1',0),ResponsesFixture)
        (folder/'token').write_text('fixture-token',encoding='utf-8')
        (folder/'runtime-modes.json').write_text('{"codex-hook":"protect"}',encoding='utf-8')
        command=subprocess.list2cmdline([sys.executable,str(ROOT/'guardian/codex_hook.py'),'--port',str(guard.server_port),'--token-file',str(folder/'token')])
        config='model="gpt-5"\nmodel_provider="fixture"\napproval_policy="never"\nsandbox_mode="workspace-write"\nweb_search="disabled"\n[analytics]\nenabled=false\n[features]\nenable_request_compression=false\napply_patch_freeform=true\n[model_providers.fixture]\nname="Local fixture"\nwire_api="responses"\nbase_url='+json.dumps(f'http://127.0.0.1:{model.server_port}/v1')+'\nenv_key="GUARDIAN_FIXTURE_KEY"\n'
        config+='[windows]\nsandbox="unelevated"\n'
        for event in ('PreToolUse','PostToolUse'):
            config+='[[hooks.'+event+']]\nmatcher="apply_patch"\n[[hooks.'+event+'.hooks]]\ntype="command"\ncommand='+json.dumps(command)+'\ntimeout=4\n'
        (home/'config.toml').write_text(config,encoding='utf-8')
        for server in (guard,model):threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            for name,body,expected in [('add-normal','*** Add File: demo.txt\n+CODEX_PATCH_FIXTURE','pass'),
                                      ('add-sensitive','*** Add File: .env\n+SYNTHETIC=fixture','review'),
                                      ('delete-normal','*** Delete File: demo.txt','review'),
                                      ('approved-retry-once','*** Add File: .env\n+SYNTHETIC=fixture','review')]:
                model.patch='*** Begin Patch\n'+body+'\n*** End Patch';model.results=[];model.requests=0;model.offered_tools=[]
                before={e['event_id'] for e in engine.events()}
                model.retry_approval=name=='approved-retry-once';model.engine=engine;model.before=before
                try:
                    result=subprocess.run([str(executables[0]),'exec','--ephemeral','--skip-git-repo-check','--json','--sandbox','workspace-write','-C',str(workspace),
                        'Apply only the single synthetic patch supplied by the local fixture, then stop.'],env=env,cwd=workspace,
                        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
                except subprocess.TimeoutExpired:
                    rows.append({'case':name,'passed':False,'timed_out':True,'model_requests':model.requests});break
                events=[e for e in engine.events() if e['event_id'] not in before]
                intact=(workspace/'demo.txt').exists() and (workspace/'demo.txt').read_text(encoding='utf-8').strip()=='CODEX_PATCH_FIXTURE'
                row={'case':name,'exit_code':result.returncode,'model_requests':model.requests,'tool_offered':'apply_patch' in model.offered_tools,
                     'tool_result_received':bool(model.results),'events':[{k:e.get(k) for k in ('tool_name','verdict','execution_state','findings')} for e in events],
                     'normal_file_intact':intact,'sensitive_file_absent':not (workspace/'.env').exists()}
                row['guardian_denial_returned']=any('Guardian:' in json.dumps(output) for output in model.results)
                receipt_ok=len(events)==1 and (events[0]['execution_state']=='tool_returned' if expected=='pass' else row['guardian_denial_returned'])
                row['passed']=result.returncode==0 and row['tool_offered'] and bool(model.results) and len(events)==1 and events[0]['verdict']==expected and receipt_ok and intact and row['sensitive_file_absent']
                if model.retry_approval:
                    granted=[e for e in events if e['verdict']=='pass']
                    reviewed=[e for e in events if e['verdict']=='review']
                    row['synthetic_sensitive_file_exact']=(workspace/'.env').exists() and (workspace/'.env').read_text(encoding='utf-8').strip()=='SYNTHETIC=fixture'
                    row['approved_retry_linked']=len(granted)==1 and any(granted[0].get('approved_from')==e['event_id'] for e in reviewed)
                    row['passed']=(result.returncode==0 and row['tool_offered'] and model.requests==4 and len(events)==3
                        and len(reviewed)==2 and len(granted)==1 and granted[0]['execution_state']=='tool_returned'
                        and row['approved_retry_linked'] and row['synthetic_sensitive_file_exact'] and intact)
                expected_contexts={digest(['cwd-v1',str(workspace)]),digest(['cwd-v1',workspace.as_posix()])}
                row['working_directory_bound']=bool(events) and all(e.get('working_directory_context')=='reported' and e.get('execution_context_digest') in expected_contexts for e in events)
                row['passed']=row['passed'] and row['working_directory_bound']
                if not row['passed']:row['diagnostic']=(result.stderr+result.stdout)[-2500:]
                rows.append(row);print(json.dumps(row),flush=True)
                if not row['passed']:break
        finally:
            for server in (guard,model):server.shutdown();server.server_close()
            engine.close()
    report={'version':version,'scope':'isolated temporary Codex home/workspace with fixed loopback model, no real user data',
            'cases':rows,'passed':len(rows)==4 and all(r['passed'] for r in rows)}
    (ROOT/'.local/codex-patch-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
