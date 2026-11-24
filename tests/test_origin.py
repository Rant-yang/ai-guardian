import json
import unittest
from unittest.mock import patch
from guardian.origin import Origins
from guardian.engine import Engine

SESSION='12345678-1234-4234-8234-123456789abc'


class OriginTests(unittest.TestCase):
    def test_unsupported_navigation_is_distinct_from_missing_event_locator(self):
        for adapter in ('qoder-hook','gemini-hook','unknown'):
            with patch('guardian.origin.os.startfile',create=True) as launch:
                result=self.origins.open({'event_id':'unsupported','source_adapter':adapter,'is_demo':False})
            launch.assert_not_called()
            self.assertEqual(result['kind'],'unsupported')
            self.assertFalse(result['visible_session_verified'])
            self.assertNotIn('command',result)

    def test_pi_resume_requires_persistence_and_never_launches_command(self):
        for persisted in (True,False,'true'):
            event=self.event('pi-extension')
            with patch.object(self.origins.windows,'capture',return_value=None):
                self.origins.remember(event,'fixture-session',42,resume_available=persisted)
            with patch('guardian.origin.os.startfile',create=True) as launch:result=self.origins.open(event)
            launch.assert_not_called()
            self.assertEqual(result.get('command'),'pi --session fixture-session' if persisted is True else None)
            self.assertFalse(result['visible_session_verified'])
            self.origins.forget([event['event_id']])
        for session in ('-inject','a;calc','a b','../file','a"b','fixture.jsonl'):
            event={'event_id':session,'source_adapter':'pi-extension','is_demo':False}
            self.origins.remember(event,session,resume_available=True)
            self.assertEqual(self.origins.locate(event)['kind'],'unavailable')

    def setUp(self):
        self.engine=Engine(':memory:');self.addCleanup(self.engine.close)
        self.origins=Origins()

    def event(self,adapter='codex-hook',session=SESSION,demo=False):
        return self.engine.evaluate({'session_id':session,'tool_use_id':'one','tool_name':'Read','tool_input':{}},adapter=adapter,demo=demo)

    def test_exact_fixed_codex_link_without_persisting_raw_identity(self):
        event=self.event();self.origins.remember(event,SESSION)
        self.assertNotIn(SESSION,json.dumps(self.engine.events()))
        with patch('guardian.origin.os.name','nt'),patch('guardian.origin.os.startfile',create=True) as launch:
            result=self.origins.open(event)
            launch.assert_called_once_with('codex://threads/'+SESSION)
        self.assertTrue(result['requested']);self.assertFalse(result['visible_session_verified'])
        self.assertEqual(result['command'],'codex resume '+SESSION)

    def test_bad_identity_demo_expiry_and_unknown_events_never_launch(self):
        for session in ('https://evil.invalid','../other','x;calc','12345678-1234-4234-8234-123456789abc?prompt=run'):
            event=self.event(session=session);self.origins.remember(event,session)
            self.assertEqual(self.origins.locate(event)['kind'],'unavailable')
        event=self.event(demo=True);self.origins.remember(event,SESSION)
        self.assertEqual(self.origins.locate(event)['kind'],'unavailable')
        event=self.event()
        with patch('guardian.origin.time.monotonic',return_value=0):self.origins.remember(event,SESSION)
        with patch('guardian.origin.time.monotonic',return_value=86401):
            self.assertEqual(self.origins.locate(event)['kind'],'unavailable')
        self.assertEqual(Origins().locate(event)['kind'],'unavailable')

    def test_manual_clients_do_not_launch_or_resume(self):
        for adapter,session,prefix in [('claude-hook',SESSION,'claude --resume '),('opencode-plugin','ses_fixture12345','opencode --session ')]:
            event=self.event(adapter,session);self.origins.remember(event,session)
            with patch('guardian.origin.os.startfile',create=True) as launch:result=self.origins.open(event)
            launch.assert_not_called();self.assertEqual(result['command'],prefix+session)

    def test_terminal_hint_is_ephemeral_immutable_and_not_session_verification(self):
        event=self.event('claude-hook')
        with patch.object(self.origins.windows,'capture',return_value={'pid':30,'created':100,'hwnd':42}) as capture:
            self.origins.remember(event,SESSION,10)
            self.origins.remember(event,SESSION,999)
            capture.assert_called_once_with(10)
        self.assertNotIn('source_pid',json.dumps(self.engine.events()))
        with patch.object(self.origins.windows,'activate',return_value={'window_foreground_verified':True}) as activate:
            result=self.origins.open(event)
            self.assertTrue(result['window_foreground_verified']);self.assertFalse(result['visible_session_verified'])
            self.assertIn('claude --resume',result['command']);activate.assert_called_once()
        self.origins.forget([event['event_id']]);self.assertEqual(self.origins.window_rows,{})
        self.assertEqual(self.origins.open(event)['kind'],'unavailable')

    def test_os_failure_is_not_reported_as_opened(self):
        event=self.event();self.origins.remember(event,SESSION)
        with patch('guardian.origin.os.name','nt'),patch('guardian.origin.os.startfile',side_effect=OSError,create=True):
            result=self.origins.open(event)
            self.assertFalse(result['requested'])
            self.assertEqual(result['command'],'codex resume '+SESSION)

    def test_codex_cli_terminal_hint_does_not_open_desktop_even_if_window_is_gone(self):
        event=self.event()
        with patch.object(self.origins.windows,'capture',return_value={'pid':30,'created':100,'hwnd':42}) as capture:
            self.origins.remember(event,SESSION,10)
            capture.assert_called_once_with(10)
        for foreground in (True,False):
            with self.subTest(foreground=foreground),patch.object(self.origins.windows,'activate',return_value={'window_foreground_verified':foreground}),patch('guardian.origin.os.startfile',create=True) as launch:
                result=self.origins.open(event)
                launch.assert_not_called()
                self.assertEqual(result['command'],'codex resume '+SESSION)
                self.assertEqual(result['window_foreground_verified'],foreground)
                self.assertFalse(result['visible_session_verified'])
        self.assertNotIn('source_pid',json.dumps(self.engine.events()))
