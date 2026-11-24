"""Real isolated OpenCode + loopback fixture model; only temporary patch files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine, digest
from guardian.server import Server
from verify_claude_local import ModelHandler


def main():
    executable=Path(os.environ['APPDATA'])/'npm/node_modules/opencode-ai/bin/opencode.exe'
    if not executable.is_file():raise SystemExit('Installed OpenCode not found')
    version=subprocess.run([str(executable),'--version'],capture_output=True,text=True,timeout=10).stdout.strip()
    rows=[]
    (ROOT/'.local/test-temp').mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='patch-client-',dir=ROOT/'.local/test-temp',ignore_cleanup_errors=True) as directory:
        folder=Path(directory);engine=Engine(':memory:')
        guard=Server(('127.0.0.1',0),engine,'fixture-token');guard.integrations=lambda force=False:[]
        model=ThreadingHTTPServer(('127.0.0.1',0),ModelHandler);model.tool_name='apply_patch';model.results=[]
        (folder/'token').write_text('fixture-token',encoding='utf-8')
        config={'$schema':'https://opencode.ai/config.json','autoupdate':False,'share':'disabled',
            'plugin':[(ROOT/'integrations/opencode/guardian.mjs').as_uri()],
            'permission':{'edit':'allow'},'enabled_providers':['guardian-fixture'],'model':'guardian-fixture/gpt-5-fixture',
            'provider':{'guardian-fixture':{'npm':'@ai-sdk/anthropic','name':'Local fixture',
                'options':{'baseURL':f'http://127.0.0.1:{model.server_port}/v1','apiKey':'local-fake-key'},
                'models':{'gpt-5-fixture':{'name':'gpt-5-fixture','limit':{'context':200000,'output':1024}}}}}}
        (folder/'opencode.json').write_text(json.dumps(config),encoding='utf-8')
        env={**os.environ,'GUARDIAN_MODE':'protect','GUARDIAN_PORT':str(guard.server_port),'GUARDIAN_TOKEN_FILE':str(folder/'token'),
             'XDG_CONFIG_HOME':str(folder/'config'),'XDG_DATA_HOME':str(folder/'data'),'XDG_STATE_HOME':str(folder/'state'),
             'OPENCODE_DISABLE_AUTOUPDATE':'true','OPENCODE_DISABLE_MODELS_FETCH':'true','OPENCODE_DISABLE_DEFAULT_PLUGINS':'true',
             'OPENCODE_CONFIG':str(folder/'opencode.json')}
        for server in (guard,model):threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            cases=[('add-normal','*** Add File: demo.txt\n+PATCH_FIXTURE_ONLY','pass'),
                   ('add-sensitive','*** Add File: .env\n+SYNTHETIC_VALUE=fixture','review'),
                   ('delete-normal','*** Delete File: demo.txt','review')]
            for name,body,expected in cases:
                model.tool_input={'patchText':'*** Begin Patch\n'+body+'\n*** End Patch'}
                model.results=[];model.offered_tools=[];before={e['event_id'] for e in engine.events()}
                try:
                    result=subprocess.run([str(executable),'run','--print-logs','Apply the single synthetic patch provided by the local fixture model, once, then stop.'],
                        cwd=folder,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
                except subprocess.TimeoutExpired:
                    rows.append({'case':name,'passed':False,'timed_out':True,'tool_offered':'apply_patch' in model.offered_tools,
                                 'tool_result_received':bool(model.results)})
                    break
                events=[e for e in engine.events() if e['event_id'] not in before]
                normal=(folder/'demo.txt').exists() and (folder/'demo.txt').read_text(encoding='utf-8').strip()=='PATCH_FIXTURE_ONLY'
                row={'case':name,'exit_code':result.returncode,'tool_offered':'apply_patch' in model.offered_tools,
                    'tool_result_received':bool(model.results),'event_count':len(events),'verdicts':[e['verdict'] for e in events],
                    'receipts':[e['execution_state'] for e in events],'findings':[e['findings'] for e in events],
                    'normal_file_intact':normal,'sensitive_file_absent':not (folder/'.env').exists()}
                row['passed']=(result.returncode==0 and row['tool_offered'] and bool(model.results) and len(events)==1
                    and events[0]['tool_name']=='apply_patch' and events[0]['verdict']==expected and normal and row['sensitive_file_absent']
                    and events[0]['execution_state']==('tool_returned' if expected=='pass' else 'blocked'))
                expected_contexts={digest(['cwd-v1',str(folder)]),digest(['cwd-v1',folder.as_posix()])}
                row['working_directory_bound']=bool(events) and all(e.get('working_directory_context')=='reported' and e.get('execution_context_digest') in expected_contexts for e in events)
                row['passed']=row['passed'] and row['working_directory_bound']
                if not row['passed']:row['diagnostic']=(result.stderr+result.stdout)[-2000:]
                rows.append(row);print(json.dumps(row),flush=True)
        finally:
            for server in (guard,model):server.shutdown();server.server_close()
            engine.close()
    report={'client_version':version,'scope':'real OpenCode, loopback fixture model, temporary files only; no cloud or user configuration changes',
            'cases':rows,'passed':len(rows)==3 and all(row['passed'] for row in rows)}
    (ROOT/'.local/opencode-patch-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
