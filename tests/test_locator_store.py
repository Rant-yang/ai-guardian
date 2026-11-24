import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from guardian.locator_store import LocatorStore
from guardian.origin import Origins
from guardian.navigation import Navigation

SESSION='12345678-1234-4234-8234-123456789abc'


class LocatorStoreTests(unittest.TestCase):
    def test_pi_persistence_flag_and_terminal_identity_survive_restart_without_rebinding(self):
        store=LocatorStore(':memory:');self.addCleanup(store.close)
        for persisted in (True,False):
            event={'event_id':str(persisted),'source_adapter':'pi-extension','is_demo':False}
            origin=Origins(store)
            with patch.object(origin.windows,'capture',return_value={'pid':30,'created':100,'hwnd':42}):
                origin.remember(event,SESSION,10,resume_available=persisted)
                origin.remember(event,'different-session',999,resume_available=not persisted)
            restored=Origins(store)
            with patch.object(restored.windows,'activate',return_value={'window_foreground_verified':False,'window_reason':'closed_or_ambiguous'}):
                result=restored.open(event)
            self.assertEqual(result.get('command'),'pi --session '+SESSION if persisted else None)
            self.assertFalse(result['visible_session_verified'])
            self.assertEqual(result['window_reason'],'closed_or_ambiguous')
            self.assertIn('原项目目录' if persisted else '没有已确认的持久会话',result['message'])

    def test_restart_keeps_exact_codex_and_claude_routes_and_revalidates_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'locators.sqlite3'
            first=LocatorStore(path)
            target={'pid':30,'created':100,'hwnd':42,'console_hwnd':43,'console_pid':31,'console_created':101}
            for adapter in ('codex-hook','claude-hook'):
                event={'event_id':adapter,'source_adapter':adapter,'is_demo':False}
                origin=Origins(first)
                with patch.object(origin.windows,'capture',return_value=target):origin.remember(event,SESSION,10)
            first.close()
            second=LocatorStore(path)
            self.addCleanup(second.close)
            for adapter in ('codex-hook','claude-hook'):
                event={'event_id':adapter,'source_adapter':adapter,'is_demo':False}
                origin=Origins(second)
                with patch.object(origin.windows,'activate',return_value={'window_foreground_verified':False,'window_reason':'closed_or_ambiguous'}) as activate:
                    result=origin.open(event)
                    self.assertIn(SESSION,result['command'])
                    self.assertFalse(result['window_foreground_verified'])
                    activate.assert_called_once_with(target)
            second.close()

    def test_opencode_restart_needs_matching_instance_heartbeat(self):
        store=LocatorStore(':memory:');self.addCleanup(store.close)
        event={'event_id':'event','source_adapter':'opencode-plugin','is_demo':False}
        Navigation(store).remember(event,'ses_example12345',SESSION)
        restored=Navigation(store)
        self.assertIsNone(restored.request('event'))
        restored.heartbeat({'instance_id':SESSION,'navigation':'session_select'})
        result=restored.request('event')
        self.assertEqual(result['state'],'queued')
        restored.window_result('event',{'window_foreground_verified':True,'message':'fixture foreground'})
        self.assertTrue(restored.status('event')['window_foreground_verified'])
        delivery=restored.heartbeat({'instance_id':SESSION,'navigation':'session_select'})
        self.assertEqual(delivery['navigation']['session_id'],'ses_example12345')
        self.assertIn('fixture foreground',restored.status('event')['message'])
        restored.forget(['event'])
        self.assertIsNone(Navigation(store).request('event'))

    def test_expiry_and_first_binding_immutable(self):
        store=LocatorStore(':memory:');self.addCleanup(store.close)
        with patch('guardian.locator_store.time.time',return_value=10):
            store.put('origin','event',['first'])
            store.put('origin','event',['second'])
            self.assertEqual(store.get('origin','event')[0],['first'])
        with patch('guardian.locator_store.time.time',return_value=86411):self.assertIsNone(store.get('origin','event'))

    def test_opencode_captures_terminal_without_running_recovery_command(self):
        origin=Origins()
        event={'event_id':'event','source_adapter':'opencode-plugin','is_demo':False}
        with patch.object(origin.windows,'capture',return_value={'pid':30,'created':100,'hwnd':42}) as capture:
            origin.remember(event,'ses_example12345',10)
            capture.assert_called_once_with(10,source_names=('opencode.exe','node.exe','bun.exe'))
        with patch.object(origin.windows,'activate',return_value={'window_foreground_verified':True}):
            self.assertTrue(origin.open(event)['window_foreground_verified'])


if __name__=='__main__':unittest.main()
