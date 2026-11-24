"""Reviewed JSON command hooks. Run via absolute Python and script paths."""
import argparse
import json
import sys
import urllib.request
import uuid
import os
from pathlib import Path
if __package__:
    from .adapter_contracts import JSON_HOOK_PROTOCOLS
    from .protocol import validate_decision
    from .output_scan import scan_output
    from .service_endpoint import resolve_port
else:
    from adapter_contracts import JSON_HOOK_PROTOCOLS
    from protocol import validate_decision
    from output_scan import scan_output
    from service_endpoint import resolve_port


def decision_output(event):
    verdict = event['verdict']
    if verdict in ('deny', 'review'):
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                'permissionDecision': 'deny' if verdict == 'deny' else 'ask',
                'permissionDecisionReason': 'Agent Guardian: ' + ', '.join(event['findings'])}}
    # Never return allow: that would bypass the client's existing permission prompt.
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int)
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--mode', choices=['observe', 'protect'], default='observe')
    parser.add_argument('--client', choices=list(JSON_HOOK_PROTOCOLS), default='claude')
    options = parser.parse_args()
    protocol = JSON_HOOK_PROTOCOLS[options.client]
    post = False
    try:
        try:payload = json.loads(sys.stdin.buffer.read(262145))
        except (ValueError,UnicodeError):payload=None
        post=isinstance(payload,dict) and payload.get('hook_event_name') in protocol.receipts
        mode_file=Path(options.token_file).parent/'runtime-modes.json'
        if mode_file.exists():
            fallback=options.mode
            options.mode='protect'
            options.mode=json.loads(mode_file.read_text(encoding='utf-8')).get(options.client+'-hook',fallback)
            if options.mode not in ('observe','protect'):raise ValueError('invalid policy')
        if not isinstance(payload,dict):raise ValueError('invalid payload')
        if not post and payload.get('hook_event_name') != protocol.before:
            raise ValueError('unsupported phase')
        if options.client == 'gemini':
            payload['tool_name'] = {'run_shell_command':'Bash','read_file':'Read','write_file':'Write'}.get(payload.get('tool_name'), payload.get('tool_name'))
            # Gemini BeforeTool does not guarantee a tool-call ID; don't deduplicate distinct invocations.
            payload['tool_use_id'] = str(uuid.uuid4())
        with open(options.token_file, encoding='utf-8') as stream:
            token = stream.read().strip()
        body = json.dumps({'payload': payload, 'mode': options.mode, **({'source_pid':os.getpid()} if options.client=='claude' else {})}).encode()
        endpoint = '/api/check' if options.client=='claude' else '/api/'+options.client+'/check'
        if post:
            endpoint='/api/receipt'
            body=json.dumps({'adapter':options.client+'-hook','session_id':payload['session_id'],'call_id':payload['tool_use_id'],
                             'status':'succeeded' if payload['hook_event_name']=='PostToolUse' else 'failed',
                             'output_scan':scan_output(payload.get('tool_response'))}).encode()
        port=resolve_port(options.token_file,options.port)
        request = urllib.request.Request(f'http://127.0.0.1:{port}{endpoint}', body,
                    {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=3) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('Response too large')
            result = json.loads(raw)
        if post:
            print('{}')
            return
        validate_decision(result)
        options.mode=result['mode']
        if options.client == 'gemini':
            print(json.dumps({'decision':'deny','reason':'Guardian: '+', '.join(result['findings'])} if result['verdict'] in ('deny','review') else {}))
        else:
            print(json.dumps(decision_output(result)))
    except Exception:
        # Do not print raw parameters, tokens, file paths, or remote error bodies.
        if post or options.mode == 'observe':
            print(json.dumps({'systemMessage': 'Guardian unavailable: observation incomplete. Guardian is not blocking this action; client permissions still apply.'}))
        elif options.client == 'gemini':
            print(json.dumps({'decision':'deny','reason':'Guardian unavailable; protection failed closed. Strict protection is enabled. Start Guardian or switch this client to observation mode.'}))
        else:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                   'permissionDecision': 'deny', 'permissionDecisionReason': 'Guardian unavailable; protection failed closed. Strict protection is enabled. Start Guardian or switch this client to observation mode.'}}))


if __name__ == '__main__':
    main()
