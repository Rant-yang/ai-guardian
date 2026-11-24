import unittest
from datetime import datetime, timezone, timedelta
from guardian.overview import build
from guardian.engine import Engine


class OverviewTests(unittest.TestCase):
    def test_native_review_expired_or_revoked_is_not_waiting_for_user(self):
        for reason in ('expired','revoked'):
            with self.subTest(reason=reason):
                engine=Engine(':memory:');self.addCleanup(engine.close)
                event=engine.evaluate(dict(session_id='s',tool_use_id='one',tool_name='Read',
                    tool_input={'file_path':'fixture/.env'}),adapter='pi-extension')
                now=datetime.now(timezone.utc)+timedelta(seconds=301 if reason=='expired' else 31)
                if reason=='revoked':engine.revoke_approvals()
                result=build(engine.events(),[],[{'id':'pi','installed':True}],now=now)['diagnostics'][0]
                self.assertEqual(result['waiting_decisions_since_start'],0)
                self.assertEqual(result['receipt_gaps_since_start'],1)
                self.assertFalse(result['enforcement_verified'])

    def test_stopped_pending_action_remains_pending_until_decision_and_retry(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        payload=dict(session_id='s',tool_use_id='one',tool_name='Read',tool_input={'file_path':'fixture/.env'})
        event=engine.evaluate(payload,adapter='opencode-plugin')
        engine.receipt('opencode-plugin','s','one','blocked')
        def diagnostic():return build(engine.events(),[],[{'id':'opencode','installed':True}])['diagnostics'][0]
        self.assertEqual(diagnostic()['waiting_decisions_since_start'],1)
        engine.approve(event['event_id'],'approve')
        self.assertEqual(diagnostic()['waiting_decisions_since_start'],0)
        self.assertEqual(diagnostic()['authorized_retries_since_start'],1)
        engine.evaluate({**payload,'tool_use_id':'retry'},adapter='opencode-plugin')
        self.assertEqual(diagnostic()['authorized_retries_since_start'],0)
        self.assertEqual(diagnostic()['outstanding_actions_since_start'],1)

    def test_terminal_approval_without_stop_receipt_is_not_still_pending(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        event=engine.evaluate(dict(session_id='s',tool_use_id='one',tool_name='Read',
                                  tool_input={'file_path':'fixture/.env'}),adapter='codex-hook')
        engine.approve(event['event_id'],'reject')
        result=build(engine.events(),[],[{'id':'codex-native','installed':True}],
                     now=datetime.now(timezone.utc)+timedelta(seconds=31))['diagnostics'][0]
        self.assertEqual(result['waiting_decisions_since_start'],0)
        self.assertEqual(result['authorized_retries_since_start'],0)
        self.assertEqual(result['receipt_gaps_since_start'],1)

    def test_native_confirmation_ends_when_tool_receipt_arrives(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        engine.evaluate(dict(session_id='s',tool_use_id='one',tool_name='Read',
                             tool_input={'file_path':'fixture/.env'}),adapter='claude-hook')
        rows=[{'id':'claude','installed':True}]
        self.assertEqual(build(engine.events(),[],rows)['diagnostics'][0]['waiting_decisions_since_start'],1)
        engine.receipt('claude-hook','s','one','tool_returned')
        self.assertEqual(build(engine.events(),[],rows)['diagnostics'][0]['waiting_decisions_since_start'],0)

    def test_mixed_plugin_revisions_need_restart_even_when_heartbeats_are_online(self):
        clients=[{'id':'opencode','installed':True}]
        connections=[{'adapter':'opencode-plugin','online':True,'revision_current':True},
                     {'adapter':'opencode-plugin','online':True,'revision_current':False}]
        diagnostic=build([],connections,clients)['diagnostics'][0]
        self.assertEqual(diagnostic['readiness'],'adapter_refresh_required')
        self.assertEqual(diagnostic['outdated_online_instances'],1)
        self.assertEqual(diagnostic['online_instances'],2)
        connections[1]['online']=False
        self.assertEqual(build([],connections,clients)['diagnostics'][0]['readiness'],'awaiting_event')
        self.assertFalse(diagnostic['enforcement_verified'])

    def test_receipt_from_one_session_does_not_hide_another_session(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        for session in ('completed','still-running'):
            engine.evaluate(dict(session_id=session,tool_use_id='one',tool_name='Read',
                                 tool_input={'file_path':'fixture/readme.md'}),adapter='codex-hook')
        engine.receipt('codex-hook','completed','one','tool_returned')
        events=engine.events();now=datetime.now(timezone.utc)
        rows=[{'id':'codex-native','installed':True}]
        within_grace=build(events,[],rows,now=now)['diagnostics'][0]
        self.assertEqual(within_grace['readiness'],'receiving')
        self.assertEqual(within_grace['outstanding_actions_since_start'],1)
        overdue=build(events,[],rows,now=now+timedelta(seconds=31))['diagnostics'][0]
        self.assertEqual(overdue['readiness'],'receipt_gaps')
        self.assertEqual(overdue['receipt_gaps_since_start'],1)
        self.assertEqual(overdue['receipt_gap_sessions'],1)
        engine.receipt('codex-hook','still-running','one','tool_returned')
        self.assertEqual(build(engine.events(),[],rows,now=now+timedelta(seconds=31))['diagnostics'][0]['readiness'],'receiving')

    def test_pending_review_and_old_records_are_not_execution_receipt_gaps(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        engine.evaluate(dict(session_id='pending',tool_use_id='one',tool_name='Read',
                             tool_input={'file_path':'fixture/.env'}),adapter='claude-hook')
        now=datetime.now(timezone.utc)+timedelta(seconds=60)
        rows=[{'id':'claude','installed':True}]
        result=build(engine.events(),[],rows,now=now)['diagnostics'][0]
        self.assertEqual(result['receipt_gaps_since_start'],0)
        self.assertEqual(result['waiting_decisions_since_start'],1)
        historical=build(engine.events(),[],rows,now=now,started_at=now)['diagnostics'][0]
        self.assertEqual(historical['waiting_decisions_since_start'],0)

    def test_health_separates_history_demo_receipts_and_current_activity(self):
        engine=Engine(':memory:')
        self.addCleanup(engine.close)
        payload=dict(session_id='fixture',tool_use_id='one',tool_name='Read',tool_input={})
        engine.evaluate(payload,adapter='codex-hook')
        engine.receipt('codex-hook','fixture','one','tool_returned')
        events=engine.events();now=datetime.now(timezone.utc)+timedelta(seconds=1)
        rows=[{'id':'codex-native','installed':True}]
        historical=build(events,[],rows,started_at=now,modes={'codex-hook':'protect'})['diagnostics'][0]
        self.assertEqual(historical['readiness'],'history_only')
        self.assertEqual(historical['receipts_since_start'],0)
        self.assertEqual(historical['configured_mode'],'protect')
        self.assertFalse(historical['heartbeat_supported'])
        current=build(events,[],rows,started_at=now-timedelta(minutes=1))['diagnostics'][0]
        self.assertEqual(current['readiness'],'receiving')
        self.assertEqual(current['receipts_since_start'],1)
        self.assertFalse(current['enforcement_verified'])
        self.assertEqual(current['trust_status'],'unknown')
        events[0]['is_demo']=True
        demo=build(events,[],rows)['diagnostics'][0]
        self.assertEqual(demo['readiness'],'awaiting_event')
        self.assertEqual(demo['events_in_window'],0)

    def test_missing_receipt_and_lost_heartbeat_do_not_claim_protection(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        engine.evaluate(dict(session_id='s',tool_use_id='c',tool_name='Read',tool_input={}),adapter='opencode-plugin')
        rows=[{'id':'opencode','installed':True}]
        self.assertEqual(build(engine.events(),[],rows)['diagnostics'][0]['readiness'],'awaiting_receipt')
        result=build(engine.events(),[{'adapter':'opencode-plugin','online':False}],rows)['diagnostics'][0]
        self.assertEqual(result['readiness'],'heartbeat_lost')
        self.assertEqual(result['online_instances'],0)

    def test_sessions_do_not_merge_clients_or_demo(self):
        engine=Engine(':memory:')
        try:
            payload=dict(session_id='same',tool_use_id='one',tool_name='Read',tool_input={})
            for adapter,demo in [('claude-hook',False),('gemini-hook',False),('claude-hook',True)]:
                engine.evaluate(payload,adapter=adapter,demo=demo)
            result=build(engine.events(),[],[{'id':'claude','installed':True}])
            self.assertEqual(len(result['sessions']),3)
            self.assertEqual(result['diagnostics'][0]['state'],'observed')
            self.assertFalse(result['diagnostics'][0]['enforcement_verified'])
        finally:engine.close()

    def test_checks_only_adapter_never_claims_receipts_or_reports_unsupported_gap(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        engine.evaluate(dict(session_id='s',tool_use_id='one',tool_name='Read',tool_input={}),adapter='gemini-hook')
        result=build(engine.events(),[],[{'id':'gemini','installed':True}],now=datetime.now(timezone.utc)+timedelta(minutes=3))['diagnostics'][0]
        self.assertEqual(result['readiness'],'checks_only')
        self.assertFalse(result['receipt_supported'])
        self.assertEqual(result['receipt_gaps_since_start'],0)

    def test_old_activity_or_mode_mismatch_cannot_confirm_current_connection(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        engine.evaluate(dict(session_id='s',tool_use_id='one',tool_name='Read',tool_input={}),adapter='claude-hook',mode='observe')
        engine.receipt('claude-hook','s','one','succeeded')
        rows=[{'id':'claude','installed':True}];now=datetime.now(timezone.utc)
        changed=build(engine.events(),[],rows,now=now,modes={'claude-hook':'protect'})['diagnostics'][0]
        self.assertEqual(changed['readiness'],'mode_unverified')
        idle=build(engine.events(),[],rows,now=now+timedelta(minutes=6),modes={'claude-hook':'observe'})['diagnostics'][0]
        self.assertEqual(idle['readiness'],'idle_unverified')
        self.assertTrue(idle['receipt_supported']);self.assertEqual(idle['receipts_since_start'],1)
        engine.evaluate(dict(session_id='s',tool_use_id='two',tool_name='Read',tool_input={}),adapter='claude-hook',mode='protect')
        engine.receipt('claude-hook','s','two','succeeded')
        self.assertEqual(build(engine.events(),[],rows,modes={'claude-hook':'protect'})['diagnostics'][0]['readiness'],'receiving')

    def test_config_and_live_state_are_independent(self):
        rows=[{'id':'opencode','installed':False},{'id':'gemini','installed':True},
              {'id':'claude','installed':False,'outdated':True},{'id':'codex','installed':False,'conflict':True}]
        result=build([], [{'adapter':'opencode-plugin','online':True}],rows)
        self.assertEqual([r['state'] for r in result['diagnostics']],
                         ['disabled','awaiting_event','upgrade_required','config_error'])
