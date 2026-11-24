import threading
import unittest
from unittest.mock import patch
from guardian.semantic_gate import SemanticGate
from guardian.engine import Engine


CONFIG={'enabled':True,'confirmed_raw_local_processing':True,'clients':['codex-hook','opencode-plugin','claude-hook','gemini-hook'],
        'port':11435,'model':'fixture:local'}

def action(identity='one',tool='Bash',args=None):
    return dict(session_id='fixture',tool_use_id=identity,tool_name=tool,tool_input=args or {'command':'python fixture.py'})


class SemanticGateTests(unittest.TestCase):
    def setUp(self):
        self.gate=SemanticGate();self.engine=Engine(':memory:');self.addCleanup(self.engine.close)
        self.addCleanup(self.gate.close)

    def prepared(self):
        self.gate.configure(CONFIG)
        with patch('guardian.semantic_gate.analyze',return_value={'status':'completed','latency_ms':10}):
            self.gate.prepare(True);self.gate.worker.join(2)
        self.assertTrue(self.gate.snapshot()['preparation']['ready'])

    def test_default_disabled_and_consent_required(self):
        with patch('guardian.semantic_gate.analyze') as model:
            self.assertEqual(self.gate.evaluate(action(),'codex-hook')['status'],'disabled')
            model.assert_not_called()
        with self.assertRaises(ValueError):self.gate.configure({**CONFIG,'confirmed_raw_local_processing':False})
        self.assertFalse(self.gate.snapshot()['enabled'])

    def test_configuration_is_validated_before_invalidation_and_failure_preserves_revision(self):
        calls=[];revision=self.gate.revision
        with self.assertRaises(ValueError):self.gate.configure({'enabled':True},before_change=lambda:calls.append(True))
        self.assertEqual(calls,[])
        def fail():raise RuntimeError('invalidation failed')
        with self.assertRaises(RuntimeError):self.gate.configure(CONFIG,before_change=fail)
        self.assertEqual(self.gate.revision,revision);self.assertFalse(self.gate.snapshot()['enabled'])
        self.gate.configure(CONFIG,before_change=lambda:calls.append(True))
        self.assertEqual(calls,[True]);self.assertNotEqual(self.gate.revision,revision)

    def test_routes_skip_rules_readonly_demo_and_unselected_clients(self):
        self.gate.configure({**CONFIG,'clients':['codex-hook']})
        with patch('guardian.semantic_gate.analyze') as model:
            self.assertEqual(self.gate.evaluate(action(tool='Read'),'codex-hook')['status'],'skipped_read_only')
            self.assertEqual(self.gate.evaluate(action(args={'command':'rm -rf fixture'}),'codex-hook')['status'],'skipped_rule_decision')
            self.assertEqual(self.gate.evaluate(action(),'codex-hook',demo=True)['status'],'disabled')
            self.assertEqual(self.gate.evaluate(action(),'claude-hook')['status'],'disabled')
            model.assert_not_called()

    def test_failure_requires_review_but_observe_does_not_stop(self):
        self.prepared()
        for status in ('timeout','unavailable_or_invalid','input_too_large'):
            with patch('guardian.semantic_gate.analyze',return_value={'status':status}) as model:
                result=self.gate.evaluate(action(),'codex-hook')
            self.assertEqual(model.call_args.kwargs['timeout'],1.5)
            for mode,verdict in (('protect','review'),('observe','warn')):
                event=self.engine.evaluate(action(status+mode),adapter='codex-hook',mode=mode,semantic=result)
                self.assertEqual(event['verdict'],verdict)
                self.assertNotIn('python fixture.py',str(event))
                self.assertNotIn('fixture:local',str(event))

    def test_no_signal_cannot_override_rule_denial(self):
        self.prepared()
        with patch('guardian.semantic_gate.analyze',return_value={'status':'completed','assessment':'no_additional_signal','categories':[]}):
            result=self.gate.evaluate(action(),'codex-hook')
        event=self.engine.evaluate(action(args={'command':'rm -rf fixture'}),adapter='codex-hook',semantic=result)
        self.assertEqual(event['verdict'],'deny')

    def test_no_signal_without_task_authorization_requires_confirmation_and_exact_grant(self):
        self.prepared()
        with patch('guardian.semantic_gate.analyze',return_value={'status':'completed','assessment':'no_additional_signal','categories':[]}):
            result=self.gate.evaluate(action(),'codex-hook')
        self.assertTrue(result['requires_review'])
        self.assertEqual(result['review_reason'],'missing_task_authorization')
        pending=self.engine.evaluate(action(),adapter='codex-hook',semantic=result)
        self.assertEqual(pending['verdict'],'review')
        self.assertEqual(pending['approval_status'],'pending')
        self.assertIn('缺少用户任务授权',pending['explanations'][-1]['reason'])
        observed=self.engine.evaluate(action('observe'),adapter='codex-hook',mode='observe',semantic=result)
        self.assertEqual(observed['verdict'],'warn')
        self.engine.approve(pending['event_id'],'approve')
        changed=self.engine.evaluate(action('changed',args={'command':'python different.py'}),adapter='codex-hook',semantic=result)
        self.assertEqual(changed['verdict'],'review')
        retry=self.engine.evaluate(action('retry'),adapter='codex-hook',semantic=result)
        self.assertEqual(retry['verdict'],'pass')
        self.assertEqual(retry['approved_from'],pending['event_id'])
        self.assertEqual(self.engine.evaluate(action('again'),adapter='codex-hook',semantic=result)['verdict'],'review')
        claude=self.engine.evaluate(action('native'),adapter='claude-hook',semantic=result)
        self.assertEqual(claude['decision_state'],'awaiting_client_confirmation')

    def test_single_slot_does_not_queue_and_is_released(self):
        self.prepared();entered=threading.Event();release=threading.Event()
        def model(*args,**kwargs):entered.set();release.wait(2);return {'status':'timeout'}
        with patch('guardian.semantic_gate.analyze',side_effect=model):
            worker=threading.Thread(target=lambda:self.gate.evaluate(action(),'codex-hook'))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                result=self.gate.evaluate(action(),'codex-hook')
                self.assertEqual(result['status'],'busy');self.assertTrue(result['requires_review'])
            finally:release.set();worker.join(3)
        self.assertTrue(self.gate.slot.acquire(blocking=False));self.gate.slot.release()

    def test_approval_once_and_configuration_changes_invalidate_binding(self):
        self.prepared()
        with patch('guardian.semantic_gate.analyze',return_value={'status':'timeout'}):
            first=self.gate.evaluate(action(),'codex-hook')
            event=self.engine.evaluate(action(),adapter='codex-hook',semantic=first)
            self.engine.approve(event['event_id'],'approve')
            retry=self.engine.evaluate(action('retry'),adapter='codex-hook',semantic=first)
            self.assertEqual(retry['verdict'],'pass')
            self.assertEqual(self.engine.evaluate(action('third'),adapter='codex-hook',semantic=first)['verdict'],'review')
            pending=self.engine.evaluate(action('fourth'),adapter='codex-hook',semantic=first)
            self.engine.approve(pending['event_id'],'approve')
            self.gate.configure(CONFIG)
            stale=self.gate.finalize(first)
            self.assertEqual(stale['status'],'configuration_changed')
            new=self.gate.evaluate(action(),'codex-hook')
            self.assertEqual(self.engine.evaluate(action('fifth'),adapter='codex-hook',semantic=new)['verdict'],'review')

    def test_cold_model_does_not_load_in_action_path_and_preparation_expires(self):
        self.gate.configure(CONFIG)
        with patch('guardian.semantic_gate.analyze') as model:
            result=self.gate.evaluate(action(),'codex-hook')
            self.assertEqual(result['status'],'model_not_prepared');model.assert_not_called()
        self.prepared()
        with patch('guardian.semantic_gate.time.monotonic',return_value=self.gate.prepared_until+1):
            self.assertFalse(self.gate.snapshot()['preparation']['ready'])
            self.assertEqual(self.gate.evaluate(action(),'codex-hook')['status'],'model_not_prepared')

    def test_preparation_is_synthetic_and_late_completion_cannot_reenable(self):
        self.gate.configure(CONFIG);entered=threading.Event();release=threading.Event();seen={}
        def model(*args,**kwargs):
            seen.update(kwargs);entered.set();release.wait(2)
            return {'status':'completed','latency_ms':20}
        with patch('guardian.semantic_gate.analyze',side_effect=model):
            with self.assertRaises(ValueError):self.gate.prepare(False)
            self.gate.prepare(True)
            try:
                self.assertTrue(entered.wait(1));self.assertEqual(seen['timeout'],60)
                self.assertEqual(self.gate.evaluate(action(),'codex-hook')['status'],'model_not_prepared')
                self.gate.configure({'enabled':False})
                self.assertTrue(seen['cancel'].cancelled)
            finally:release.set();self.gate.worker.join(3)
        self.assertFalse(self.gate.snapshot()['enabled'])
        self.assertFalse(self.gate.snapshot()['preparation']['ready'])


if __name__=='__main__':unittest.main()
