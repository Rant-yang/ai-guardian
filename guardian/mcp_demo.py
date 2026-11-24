"""Minimal stdio MCP server: two synthetic tools, no file/shell/network side effects.

Only HTTP destination is the loopback Guardian service. Not a general MCP proxy.
"""
import argparse
import json
import sys
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--mode', choices=['protect','observe'], default='protect')
    args = parser.parse_args()
    session = 'mcp-demo-'+str(uuid.uuid4())
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for line in sys.stdin.buffer:
        if len(line)>65536:
            continue
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                request = {}
                continue
            if 'id' not in request:
                continue
            method = request.get('method')
            if method=='initialize':
                result = {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'guardian-safe-demo','version':'0.1.0'}}
            elif method=='ping':
                result = {}
            elif method=='tools/list':
                result = {'tools':[{'name':name,'description':description,'inputSchema':{'type':'object','properties':{},'additionalProperties':False}}
                    for name, description in [('guardian_read_demo','Read a fixed synthetic demo note. No user files are read.'),
                                              ('guardian_upload_demo','Simulate an upload under Guardian policy. No network upload happens.')]]}
            elif method=='tools/call':
                with open(args.token_file, encoding='utf-8') as stream:
                    token = stream.read().strip()
                body = {'tool':request['params']['name'],'session':session,'call_id':str(uuid.uuid4()),'mode':args.mode}
                http = urllib.request.Request(f'http://127.0.0.1:{args.port}/api/mcp/demo',json.dumps(body).encode(),
                    {'Authorization':'Bearer '+token,'Content-Type':'application/json'})
                with opener.open(http,timeout=3) as response:
                    outcome = json.load(response)
                result = {'content':[{'type':'text','text':json.dumps(outcome)}],'isError':False}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'Unknown method'}}),flush=True)
                continue
            print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
        except Exception:
            if 'id' in request:
                print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32603,'message':'Guardian demo unavailable; nothing executed'}}),flush=True)


if __name__=='__main__':
    main()
