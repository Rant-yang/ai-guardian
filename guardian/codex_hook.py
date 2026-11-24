"""Uninstalled Codex hook entry point. Run as a module only in an authorized integration."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request
if __package__:
    from .codex_adapter import normalize, decision_output
    from .protocol import validate_decision
    from .output_scan import scan_output
    from .service_endpoint import resolve_port
else:
    # Absolute-script entry works in every user's project without changing cwd.
    from codex_adapter import normalize, decision_output
    from protocol import validate_decision
    from output_scan import scan_output
    from service_endpoint import resolve_port


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--token-file',required=True)
    parser.add_argument('--port',type=int)
    args=parser.parse_args()
    mode='observe'
    post=False
    try:
        try:payload=json.loads(sys.stdin.buffer.read(262145))
        except (ValueError,UnicodeError):payload=None
        post=isinstance(payload,dict) and payload.get('hook_event_name')=='PostToolUse'
        policy=Path(args.token_file).parent/'runtime-modes.json'
        if policy.exists():
            mode='protect'
            mode=json.loads(policy.read_text(encoding='utf-8')).get('codex-hook','observe')
            if mode not in ('observe','protect'):raise ValueError('invalid mode')
        if not isinstance(payload,dict):raise ValueError('invalid payload')
        normalize(payload)
        if post:
            summary=scan_output(payload.get('tool_response'))
            payload={key:payload[key] for key in ('session_id','tool_use_id','tool_name','tool_input','hook_event_name')}
            payload['output_scan']=summary
        token=Path(args.token_file).read_text(encoding='utf-8').strip()
        port=resolve_port(args.token_file,args.port)
        request=urllib.request.Request(f'http://127.0.0.1:{port}/api/codex/check',
            json.dumps({'payload':payload,'source_pid':os.getpid()}).encode(),
            {'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request,timeout=3) as response:
            raw=response.read(65537)
            if len(raw)>65536:raise ValueError('Response too large')
            event=json.loads(raw)
        if not post:validate_decision(event)
        print(json.dumps({} if post else decision_output(event),ensure_ascii=False))
    except Exception:
        if post or mode=='observe':
            print(json.dumps({'systemMessage':'Guardian unavailable: observation incomplete.'}))
        else:
            print(json.dumps(decision_output({'mode':'protect','verdict':'deny',
                'findings':['Guardian unavailable; protection failed closed']})))


if __name__=='__main__':main()
