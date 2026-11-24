import json
from pathlib import Path
import subprocess
import sys
import tempfile
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]

class ResponseFailures(unittest.TestCase):
    def setUp(self):
        self.value={}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                body=json.dumps(owner.value).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        (self.home/'token').write_text('fixture')
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def invoke(self,client,mode,post=False,corrupt_policy=False,raw_input=None,discover_endpoint=False):
        (self.home/'runtime-modes.json').write_text('{' if corrupt_policy else json.dumps({client+'-hook':mode}))
        phase='PostToolUse' if post else 'BeforeTool' if client=='gemini' else 'PreToolUse'
        payload=dict(hook_event_name=phase,session_id='fixture',tool_use_id='one',tool_name='Read',tool_input={'file_path':'fixture'})
        command=[sys.executable,str(ROOT/'guardian'/('codex_hook.py' if client=='codex' else 'hook.py')),'--token-file',str(self.home/'token'),'--port',str(self.server.server_port)]
        if discover_endpoint:command=command[:-2]
        if client!='codex':command+=['--client',client,'--mode',mode]
        result=subprocess.run(command,input=json.dumps(payload).encode() if raw_input is None else raw_input,capture_output=True,timeout=6)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)
    def test_all_command_hooks_discover_nondefault_port_without_config_rewrite(self):
        from guardian.service_endpoint import publish
        publish(self.home,self.server.server_port)
        self.value={'mode':'protect','verdict':'pass','findings':[]}
        for client in ('claude','gemini','codex','qoder'):
            self.assertEqual(self.invoke(client,'protect',discover_endpoint=True),{})
    def test_malformed_decisions_stop_in_protection_without_mode_downgrade(self):
        for client in ('claude','gemini','codex','qoder'):
            for value in ({'verdict':'pass','findings':[]},{'mode':'observe','verdict':'unknown','findings':[]},
                          {'mode':'observe','verdict':'pass','findings':'bad'},
                          {'mode':'observe','verdict':'pass','findings':['private /path']},None):
                with self.subTest(client=client,value=value):
                    self.value=value;out=self.invoke(client,'protect')
                    decision=out.get('decision') if client=='gemini' else out.get('hookSpecificOutput',{}).get('permissionDecision')
                    self.assertEqual(decision,'deny');self.assertNotIn('private',json.dumps(out))
    def test_observation_reports_incomplete_without_deny(self):
        self.value={'mode':'invalid','verdict':'deny'}
        for client in ('claude','gemini','codex','qoder'):
            out=self.invoke(client,'observe');self.assertIn('systemMessage',out)
            self.assertNotIn('decision',out);self.assertNotIn('hookSpecificOutput',out)
    def test_corrupt_policy_on_post_never_claims_to_stop_completed_action(self):
        for client in ('claude','codex','qoder'):
            out=self.invoke(client,'protect',post=True,corrupt_policy=True)
            self.assertIn('systemMessage',out);self.assertNotIn('hookSpecificOutput',out)
    def test_valid_server_mode_change_preserves_native_permissions(self):
        self.value={'mode':'observe','verdict':'warn','findings':['outbound_transfer_review']}
        for client in ('claude','gemini','codex','qoder'):self.assertEqual(self.invoke(client,'protect'),{})

    def test_broken_input_still_uses_local_protection_mode(self):
        for client in ('claude','gemini','codex','qoder'):
            for raw in (b'{',b'null'):
                out=self.invoke(client,'protect',raw_input=raw)
                decision=out.get('decision') if client=='gemini' else out.get('hookSpecificOutput',{}).get('permissionDecision')
                self.assertEqual(decision,'deny')

    def test_offline_default_and_observation_do_not_block_but_explicit_protection_does(self):
        # Bound, non-listening socket: no Guardian server or actual file operation.
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1',0))
            command=[sys.executable,str(ROOT/'guardian/hook.py'),'--client','claude',
                     '--token-file',str(self.home/'token'),'--port',str(unavailable.getsockname()[1])]
            payload=dict(hook_event_name='PreToolUse',session_id='fixture-offline',tool_use_id='one',
                         tool_name='Read',tool_input={'file_path':'nonexistent-fixture.txt'})
            for mode in (None,'observe','protect'):
                if mode is not None:
                    (self.home/'runtime-modes.json').write_text(json.dumps({'claude-hook':mode}))
                result=subprocess.run(command,input=json.dumps(payload).encode(),capture_output=True,timeout=6)
                self.assertEqual(result.returncode,0,result.stderr)
                output=json.loads(result.stdout)
                if mode=='protect':
                    self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny')
                    self.assertIn('Start Guardian',output['hookSpecificOutput']['permissionDecisionReason'])
                else:
                    self.assertNotIn('hookSpecificOutput',output)
                    self.assertIn('client permissions still apply',output['systemMessage'])
