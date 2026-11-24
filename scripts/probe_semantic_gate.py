"""Local model + isolated HTTP pre-tool deadline probe. No tool is executed."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import threading
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine
from guardian.server import Server


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,choices=(11434,11435),default=11435)
    parser.add_argument('--model',default='qwen3:8b')
    options=parser.parse_args()
    engine=Engine(':memory:');token=secrets.token_urlsafe(32)
    server=Server(('127.0.0.1',0),engine,token)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def post(path,data,credential):
        req=urllib.request.Request(server.origin+path,json.dumps(data).encode(),
            {'Content-Type':'application/json','Authorization':'Bearer '+credential})
        with opener.open(req,timeout=3) as response:return json.load(response)
    try:
        post('/api/semantic/config',{'enabled':True,'confirmed_raw_local_processing':True,
             'clients':['opencode-plugin'],'port':options.port,'model':options.model},token)
        post('/api/semantic/prepare',{'confirmed':True},token)
        server.semantic.worker.join(65)
        preparation=server.semantic.snapshot()['preparation']
        if preparation['status']=='preparing':raise RuntimeError('Preparation exceeded budget')
        started=time.monotonic()
        event=post('/api/opencode/check',{'mode':'protect','payload':{
            'session_id':'synthetic-probe','tool_use_id':'one','tool_name':'Bash',
            'tool_input':{'command':'python fixture_only.py'}}},server.adapter_token)
        elapsed=round((time.monotonic()-started)*1000)
        report={'scope':'isolated HTTP with real local model, synthetic parameters only',
                'http_elapsed_ms':elapsed,'preparation':preparation,'verdict':event['verdict'],'semantic_check':event['semantic_check'],
                'real_actions_executed':0,'live_configuration_changed':False}
        output=ROOT/'.local/semantic-gate-probe.json';output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
        if elapsed>=3000:raise RuntimeError('Exceeded adapter deadline')
        if event['semantic_check'].get('requires_review') and event['verdict']!='review':raise RuntimeError('Unsafe fallback')
    finally:
        server.shutdown();server.server_close();worker.join();engine.close()


if __name__=='__main__':main()
