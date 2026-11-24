"""Evaluate synthetic parameter fixtures without executing commands or calling models."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guardian.rules import assess,VERSION


def evaluate(dataset):
    rows=[]
    for case in dataset['cases']:
        start=time.perf_counter()
        matches=assess(case['tool'],case['args'])
        actual=max((r['action'] for r in matches),key={'warn':1,'review':2,'deny':3}.get,default='pass')
        expected=case['expected']
        rows.append({'id':case['id'],'group':case['group'],'expected':expected,'actual':actual,
                     'match':actual==expected,'findings':list(dict.fromkeys(r['id'] for r in matches)),
                     'latency_ms':round((time.perf_counter()-start)*1000,4)})
    benign=[r for r in rows if r['expected']=='pass']
    risky=[r for r in rows if r['expected']!='pass']
    return {'dataset':dataset['name'],'scope':dataset['scope'],'policy_version':VERSION,
            'total':len(rows),'exact_matches':sum(r['match'] for r in rows),
            'benign_count':len(benign),'benign_flagged':sum(r['actual']!='pass' for r in benign),
            'risk_count':len(risky),'risk_missed':sum(r['actual']=='pass' for r in risky),
            'confusion':dict(Counter(r['expected']+' -> '+r['actual'] for r in rows)),
            'cases':rows,'real_side_effects':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',type=Path,default=ROOT/'evals/rules-development.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=evaluate(json.loads(args.dataset.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','confusion')},ensure_ascii=False))
