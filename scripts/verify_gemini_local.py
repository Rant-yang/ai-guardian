"""Isolated real Gemini CLI, fixed read-only fixture and local fake model."""
import json,os,subprocess,sys,tempfile,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine
from guardian.server import Server
import guardian.engine as engine_module

class ModelHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
        results=[part['functionResponse'] for row in request.get('contents',[]) for part in row.get('parts',[]) if 'functionResponse' in part]
        self.server.results.extend(results)
        if 'countTokens' in self.path:body={'totalTokens':100}
        else:
            part={'text':'Local fixture finished.'} if results else {'functionCall':{'name':'read_file','args':{'file_path':self.server.fixture}}}
            body={'candidates':[{'content':{'role':'model','parts':[part]},'finishReason':'STOP','index':0}],
                  'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20,'totalTokenCount':120}}
        streaming='streamGenerateContent' in self.path
        raw=(('data: '+json.dumps(body)+'\n\n') if streaming else json.dumps(body)).encode()
        self.send_response(200);self.send_header('Content-Type','text/event-stream' if streaming else 'application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

def main():
    executable=Path(os.environ['APPDATA'])/'npm/node_modules/@google/gemini-cli/bundle/gemini.js'
    if not executable.exists():raise SystemExit('Installed Gemini CLI not found')
    reports=[]
    with tempfile.TemporaryDirectory(prefix='guardian-gemini-',ignore_cleanup_errors=True) as tmp:
        folder=Path(tmp);home=folder/'home';(home/'.gemini').mkdir(parents=True)
        engine=Engine(':memory:');guard=Server(('127.0.0.1',0),engine,'fixture-token')
        model=ThreadingHTTPServer(('127.0.0.1',0),ModelHandler);model.results=[]
        for server in (guard,model):threading.Thread(target=server.serve_forever,daemon=True).start()
        (folder/'token').write_text('fixture-token')
        hook=subprocess.list2cmdline([sys.executable,str(ROOT/'guardian/hook.py'),'--client','gemini','--port',str(guard.server_port),'--token-file',str(folder/'token'),'--mode','protect'])
        (home/'.gemini/settings.json').write_text(json.dumps({'security':{'auth':{'selectedType':'gemini-api-key'}},'telemetry':{'enabled':False},'general':{'disableAutoUpdate':True},'hooks':{'BeforeTool':[{'matcher':'.*','hooks':[{'name':'guardian-fixture','type':'command','command':hook,'timeout':5000}]}]}}),encoding='utf-8')
        fixture=folder/'fixture.txt';fixture.write_text('GUARDIAN_GEMINI_READ_FIXTURE',encoding='utf-8');model.fixture=str(fixture)
        env={k:v for k,v in os.environ.items() if not k.startswith(('GEMINI_','GOOGLE_','GCLOUD_','CLOUDSDK_'))}
        env.update(GEMINI_CLI_HOME=str(home),GEMINI_CLI_TRUST_WORKSPACE='true',GOOGLE_GEMINI_BASE_URL=f'http://127.0.0.1:{model.server_port}',GEMINI_API_KEY='local-fake-key',NO_PROXY='127.0.0.1,localhost')
        original=engine_module.assess
        try:
            for case in ('normal','synthetic-deny'):
                def assess(tool,args):
                    if case=='synthetic-deny' and tool=='Read' and args.get('file_path')==str(fixture):
                        return [dict(id='fixture_execution_gate',title='Synthetic fixture',action='deny',reason='Isolated harmless read denial',impact='No real risk command')]
                    return original(tool,args)
                model.results=[];before={e['event_id'] for e in engine.events()}
                with patch.object(engine_module,'assess',side_effect=assess):
                    try:
                        result=subprocess.run(['node',str(executable),'--prompt','Read only the fixture offered by the local model once.','--model','gemini-2.5-flash','--output-format','json'],cwd=folder,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
                    except subprocess.TimeoutExpired:
                        reports.append({'case':case,'timed_out':True});break
                text=json.dumps(model.results);events=[e for e in engine.events() if e['event_id'] not in before]
                reports.append({'case':case,'exit_code':result.returncode,'model_received_tool_result':bool(model.results),
                    'read_marker_seen':'GUARDIAN_GEMINI_READ_FIXTURE' in text,'denial_seen':'fixture_execution_gate' in text,
                    'guardian_events':len(events),'verdicts':[e['verdict'] for e in events],
                    'scope':'synthetic real CLI pipeline only, no execution receipt correlation'})
                if not model.results:reports[-1]['diagnostic']=(result.stderr+result.stdout)[-1800:]
        finally:
            for server in (guard,model):server.shutdown();server.server_close()
            engine.close()
    (ROOT/'docs/gemini-local-verification.json').write_text(json.dumps(reports,indent=2),encoding='utf-8');print(json.dumps(reports,indent=2))
    return 0 if len(reports)==2 and reports[0].get('read_marker_seen') and reports[0].get('verdicts')==['pass'] and reports[1].get('denial_seen') and not reports[1].get('read_marker_seen') and reports[1].get('verdicts')==['deny'] else 1

if __name__=='__main__':raise SystemExit(main())
