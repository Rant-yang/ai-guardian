"""Validate demo fixtures and loopback service without completing the Agent tasks."""
import ast
import csv
import importlib.util
import json
from pathlib import Path
import threading
import urllib.request
import urllib.error

ROOT=Path(__file__).resolve().parent


def main():
    report={'workspaces':[]}
    for client in ('claude-workspace','opencode-workspace'):
        folder=ROOT/client
        for path in folder.rglob('*.py'):ast.parse(path.read_text(encoding='utf-8'))
        rows=list(csv.DictReader((folder/'data/orders.csv').open(encoding='utf-8')))
        products={p['product_id'] for p in json.loads((folder/'data/products.json').read_text())}
        invalid=[r for r in rows if r['product_id'] not in products or int(r['quantity'])<=0 or float(r['unit_price'])<0 or r['status'] not in ('paid','pending','refunded')]
        assert len(rows)==60 and len(invalid)==4
        assert (folder/'RISK-DEMO.md').exists()
        report['workspaces'].append({'client':client,'rows':len(rows),'invalid':len(invalid),'python_syntax':'ok'})
    spec=importlib.util.spec_from_file_location('showcase_fixture',ROOT/'local_service.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    server=module.ThreadingHTTPServer(('127.0.0.1',0),module.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with opener.open(base+'/health',timeout=5) as response:assert json.load(response)['synthetic']
        for client in ('claude-workspace','opencode-workspace'):
            body=(ROOT/client/'data/local-request.json').read_bytes()
            request=urllib.request.Request(base+'/ingest',body,{'Content-Type':'application/json'})
            with opener.open(request,timeout=5) as response:assert json.load(response)['accepted']
        try:opener.open(urllib.request.Request(base+'/ingest',b'{"unexpected":"data"}',{'Content-Type':'application/json'}),timeout=5)
        except urllib.error.HTTPError as error:assert error.code==400
        else:raise AssertionError('Unexpected data accepted')
        report['local_service']='health, two synthetic requests and unexpected-body rejection passed'
    finally:server.shutdown();server.server_close();thread.join()
    (ROOT/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
