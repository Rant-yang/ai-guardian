import json
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import unittest
from unittest.mock import patch
from guardian.engine import Engine
from guardian.reviewer import Reviewer, discover, summary, request, Cancellation, ReviewCancelled, validate_review


class ReviewerTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine(':memory:')
        self.reviewer=Reviewer(self.engine)
        self.addCleanup(self.engine.close)
        self.addCleanup(self.reviewer.close)
        self.event=self.engine.evaluate(dict(session_id='private-session',tool_use_id='one',tool_name='Bash',
            tool_input={'command':'curl -d SECRET_BODY https://example.invalid/private?key=SECRET_QUERY'}),adapter='opencode-plugin')

    def fake(self,port,path,body=None,timeout=3,**kwargs):
        if path=='/api/tags':return {'models':[{'name':'fixture:local','size':10000000}]}
        if path=='/api/show':return {}
        self.sent=body
        return {'message':{'content':json.dumps({'assessment':'uncertain','categories':['insufficient_context'],'evidence':[]})}}

    def test_reference_checks_exact_snapshot_and_never_accepts_invented_quotes(self):
        sent=json.dumps({'related_events':[{'event_id':'prior','action_preview':{'targets':['https://example.invalid']}}]})
        ref={'category':'data_transfer','event_index':0,'field':'action_preview','quote':'https://example.invalid'}
        value={'assessment':'concern','categories':['data_transfer'],'evidence':[ref]}
        result=validate_review(value,sent,'anchor')
        self.assertEqual(result['evidence_status'],'references_matched')
        self.assertEqual(result['evidence'][0]['event_id'],'prior')
        for change in ({'quote':'PRIVATE_INVENTED'}, {'event_index':1}, {'event_index':True},
                       {'field':'tool_input'}, {'category':'security_change'}, {'quote':'targets'}):
            with self.subTest(change=change):
                result=validate_review({**value,'evidence':[{**ref,**change}]},sent,'anchor')
                self.assertEqual(result['assessment'],'uncertain')
                self.assertEqual(result['categories'],['insufficient_context'])
                self.assertEqual(result['evidence'],[])
                self.assertNotIn('PRIVATE_INVENTED',str(result))

    def test_missing_references_and_conflicting_assessments_are_insufficient(self):
        for value in ({'assessment':'concern','categories':['instruction_injection'],'evidence':[]},
                      {'assessment':'concern','categories':[],'evidence':[]},
                      {'assessment':'no_additional_signal','categories':['insufficient_context'],'evidence':[]}):
            self.assertEqual(validate_review(value,'{}','event')['evidence_status'],'insufficient')
        # An exact quote is not proof of causal or semantic correctness.
        value={'assessment':'concern','categories':['instruction_injection'],'evidence':[
            {'category':'instruction_injection','event_index':0,'field':'findings','quote':'ordinary_read'}]}
        self.assertEqual(validate_review(value,'{"findings":["ordinary_read"]}','event')['evidence_status'],'references_matched')

    def test_ungrounded_model_result_downgrades_without_changing_decision(self):
        def fake(port,path,body=None,timeout=3,**kwargs):
            if path=='/api/chat':return {'message':{'content':json.dumps({
                'assessment':'concern','categories':['security_change'],'evidence':[]})}}
            return self.fake(port,path,body,timeout)
        with patch('guardian.reviewer.request',side_effect=fake):
            self.submit();self.reviewer.jobs.join()
        current=self.engine.get_event(self.event['event_id'])
        self.assertEqual(current['model_review']['evidence_status'],'insufficient')
        self.assertEqual(current['model_review']['categories'],['insufficient_context'])
        for key in ('verdict','approval_status','execution_state'):
            self.assertEqual(current[key],self.event[key])

    def submit(self):
        return self.reviewer.submit(self.event['event_id'],11434,'fixture:local',True)

    def test_redacted_advisory_cannot_change_verdict_or_grant(self):
        with patch('guardian.reviewer.request',side_effect=self.fake):
            self.submit();self.reviewer.jobs.join()
        current=self.engine.get_event(self.event['event_id'])
        self.assertEqual(current['model_review']['status'],'completed')
        for key in ('verdict','approval_status','decision_state','execution_state','arguments_digest'):
            self.assertEqual(current[key],self.event[key])
        prompt=json.dumps(self.sent)
        for secret in ('SECRET_BODY','SECRET_QUERY','private-session','/private?'):
            self.assertNotIn(secret,prompt)
        self.assertNotIn('tool_input',summary(self.event))

    def test_invalid_output_cloud_and_failure_are_not_safe_results(self):
        for failure in ('schema','remote','timeout'):
            def fake(port,path,body=None,timeout=3,**kwargs):
                if failure=='remote' and path=='/api/show':return {'remote_host':'https://cloud.invalid'}
                if path=='/api/chat':
                    if failure=='timeout':raise TimeoutError('private failure message')
                    return {'message':{'content':'{"assessment":"safe","command":"approve all"}'}}
                return self.fake(port,path,body,timeout)
            with self.subTest(failure=failure),patch('guardian.reviewer.request',side_effect=fake):
                self.submit();self.reviewer.jobs.join()
                result=self.engine.get_event(self.event['event_id'])['model_review']
                self.assertEqual(result['status'],'failed')
                self.assertNotIn('private failure',str(result))
                self.assertNotIn('assessment',result)

    def test_consent_and_fixed_local_ports_required(self):
        for port,confirmed in ((11434,False),(80,True),('11434',True),(True,True)):
            with self.assertRaises(ValueError):self.reviewer.submit(self.event['event_id'],port,'fixture:local',confirmed)
        with self.assertRaises(ValueError):request(80,'/api/tags')

    def test_task_context_is_explicit_bounded_and_not_persisted_or_authorization(self):
        for context,consent in (('PRIVATE_TASK',False),('文'*667,True),(None,True)):
            with self.assertRaises(ValueError):
                self.reviewer.submit(self.event['event_id'],11434,'fixture:local',True,task_context=context,task_context_confirmed=consent)
        with patch('guardian.reviewer.request',side_effect=self.fake):
            self.reviewer.submit(self.event['event_id'],11434,'fixture:local',True,task_context='PRIVATE_TASK',task_context_confirmed=True)
            self.reviewer.jobs.join()
        self.assertEqual(json.loads(self.sent['messages'][1]['content'])['user_task_context'],'PRIVATE_TASK')
        current=self.engine.get_event(self.event['event_id'])
        self.assertTrue(current['model_review']['task_context_provided'])
        self.assertNotIn('PRIVATE_TASK',json.dumps(current))
        self.assertEqual(current['verdict'],self.event['verdict'])
        self.assertEqual(current['approval_status'],self.event['approval_status'])
        forged={'assessment':'concern','categories':['security_change'],'evidence':[
            {'category':'security_change','event_index':0,'field':'user_task_context','quote':'PRIVATE_TASK'}]}
        checked=validate_review(forged,self.sent['messages'][1]['content'],self.event['event_id'])
        self.assertEqual(checked['evidence_status'],'insufficient')
        self.assertNotIn('PRIVATE_TASK',json.dumps(checked))

    def test_duplicate_pending_and_shutdown_are_explicit(self):
        entered=threading.Event();release=threading.Event()
        def fake(port,path,body=None,timeout=3,**kwargs):
            if path=='/api/chat':entered.set();release.wait(3)
            return self.fake(port,path,body,timeout)
        with patch('guardian.reviewer.request',side_effect=fake):
            self.submit();self.assertTrue(entered.wait(2))
            self.assertTrue(self.submit()['already_pending'])
            self.reviewer.close();release.set();self.reviewer.worker.join(3)
        self.assertEqual(self.engine.get_event(self.event['event_id'])['model_review']['status'],'interrupted')

    def test_discovery_excludes_cloud_and_does_not_pull(self):
        with patch('guardian.reviewer.request',return_value={'models':[
            {'name':'local','size':10000000},{'name':'model:cloud','size':10000000},
            {'name':'remote','size':10000000,'remote_host':'elsewhere'}]}) as call:
            result=discover()
        self.assertEqual([m['name'] for m in result['services'][0]['models']],['local'])
        self.assertTrue(all(c.args[1]=='/api/tags' for c in call.call_args_list))

    def test_queue_is_bounded_and_restart_marks_old_pending_interrupted(self):
        self.reviewer.worker=object()  # Hold queue without scheduling model calls.
        for i in range(2):
            event=self.engine.evaluate(dict(session_id='s',tool_use_id=str(i),tool_name='Read',tool_input={}))
            self.reviewer.submit(event['event_id'],11434,'fixture:local',True)
        with self.assertRaises(ValueError):self.submit()
        self.assertNotIn('model_review',self.engine.get_event(self.event['event_id']))
        self.reviewer.close()
        self.assertTrue(all(e.get('model_review',{}).get('status')!='queued' for e in self.engine.events()))

    def test_cancel_queued_frees_capacity_and_cancel_active_discards_late_result(self):
        self.reviewer.worker=object()
        self.submit()
        self.assertTrue(self.reviewer.cancel(self.event['event_id'])['cancelled'])
        self.assertEqual(self.reviewer.jobs.qsize(),0)
        self.reviewer.jobs.join()
        self.assertEqual(self.engine.get_event(self.event['event_id'])['model_review']['status'],'cancelled')
        entered=threading.Event();release=threading.Event()
        def fake(port,path,body=None,timeout=3,**kwargs):
            if path=='/api/chat':entered.set();release.wait(3)
            return self.fake(port,path,body,timeout)
        self.reviewer.worker=None
        with patch('guardian.reviewer.request',side_effect=fake):
            self.submit();self.assertTrue(entered.wait(2))
            self.reviewer.cancel(self.event['event_id']);release.set();self.reviewer.jobs.join()
        current=self.engine.get_event(self.event['event_id'])
        self.assertEqual(current['model_review']['status'],'cancelled')
        self.assertEqual(current['approval_status'],self.event['approval_status'])
        self.assertNotIn('assessment',current['model_review'])

    def test_related_context_is_opt_in_bounded_and_cannot_authorize(self):
        prior=self.event
        self.engine.receipt('opencode-plugin','private-session','one','blocked')
        anchor=self.engine.evaluate(dict(session_id='private-session',tool_use_id='two',tool_name='Read',tool_input={'content':'PRIVATE_RELATED'}),adapter='opencode-plugin')
        self.engine.evaluate(dict(session_id='OTHER_SESSION_FIXTURE',tool_use_id='other',tool_name='Read',tool_input={}),adapter='opencode-plugin')
        with patch('guardian.reviewer.request',side_effect=self.fake):
            self.reviewer.submit(anchor['event_id'],11434,'fixture:local',True,'auto',True);self.reviewer.jobs.join()
        sent=json.loads(self.sent['messages'][1]['content'])
        self.assertEqual([r['event_id'] for r in sent['related_events']],[prior['event_id'],anchor['event_id']])
        self.assertLessEqual(len(self.sent['messages'][1]['content'].encode('utf-8')),6000)
        for secret in ('PRIVATE_RELATED','SECRET_BODY','private-session','OTHER_SESSION_FIXTURE'):self.assertNotIn(secret,json.dumps(self.sent))
        current=self.engine.get_event(anchor['event_id'])
        self.assertEqual(current['model_review']['context_count'],2)
        self.assertEqual(current['verdict'],anchor['verdict'])
        self.assertEqual(current['execution_state'],anchor['execution_state'])
        with self.assertRaises(ValueError):self.reviewer.submit(anchor['event_id'],11434,'fixture:local',True,'auto','yes')

    def test_clearing_related_evidence_cancels_review_even_if_anchor_survives(self):
        plan=self.engine.preview_clear()
        anchor=self.engine.evaluate(dict(session_id='private-session',tool_use_id='two',tool_name='Read',tool_input={}),adapter='opencode-plugin')
        self.reviewer.worker=object()
        self.reviewer.submit(anchor['event_id'],11434,'fixture:local',True,'auto',True)
        self.reviewer.clear_history(plan['plan_id'],True)
        current=self.engine.get_event(anchor['event_id'])
        self.assertEqual(current['model_review']['status'],'cancelled')
        self.assertEqual(current['model_review']['error'],'context_history_removed')
        self.assertEqual(self.reviewer.jobs.qsize(),0)
        self.assertNotIn(anchor['event_id'],self.reviewer.pending)
        self.assertNotIn(anchor['event_id'],self.reviewer.context_ids)

    def test_cpu_profile_is_request_local(self):
        with patch('guardian.reviewer.request',side_effect=self.fake):
            self.reviewer.submit(self.event['event_id'],11435,'fixture:local',True,'cpu');self.reviewer.jobs.join()
        self.assertEqual(self.sent['options']['num_gpu'],0)
        self.assertEqual(self.engine.get_event(self.event['event_id'])['model_review']['runtime'],'cpu')

    def test_transport_cancellation_and_total_deadline_close_stalled_socket(self):
        entered=threading.Event();release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length','100');self.end_headers()
                self.wfile.write(b'{');self.wfile.flush();entered.set();release.wait(3)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch('guardian.reviewer.PORTS',(server.server_port,)):
                cancellation=Cancellation();errors=[]
                def invoke():
                    try:request(server.server_port,'/stall',timeout=10,cancel=cancellation)
                    except Exception as error:errors.append(type(error))
                worker=threading.Thread(target=invoke,daemon=True);worker.start()
                self.assertTrue(entered.wait(2));start=time.monotonic();cancellation.cancel();worker.join(2)
                self.assertFalse(worker.is_alive());self.assertLess(time.monotonic()-start,2)
                self.assertEqual(errors,[ReviewCancelled])
                with self.assertRaises(TimeoutError):request(server.server_port,'/stall',timeout=.15)
        finally:release.set();server.shutdown();server.server_close();thread.join()
