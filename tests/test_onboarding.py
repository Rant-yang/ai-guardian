import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from guardian.onboarding import Onboarding


class OnboardingTests(unittest.TestCase):
    def test_foreign_shell_risk_visible_for_every_hook_adapter_and_preserved(self):
        for client in ('claude','codex','gemini','qoder'):
            with self.subTest(client=client):
                path=self.flow.target(client);path.parent.mkdir(parents=True,exist_ok=True)
                event='BeforeTool' if client=='gemini' else 'PreToolUse'
                foreign={'type':'command','command':"$scriptPath = Join-Path $env:USERPROFILE 'private-secret-path'; exit 0",'shell':'powershell'}
                original={'hooks':{event:[{'hooks':[foreign]}]},'private_setting':'keep-me'}
                path.write_text(json.dumps(original),encoding='utf-8')
                before=path.read_bytes()
                plan=self.flow.preview([client])
                report=plan['clients'][0]['preflight']
                self.assertEqual(report['third_party_check'],'shell_hints_only')
                self.assertTrue(any('PowerShell' in w for w in report['warnings']))
                self.assertNotIn('private-secret-path',json.dumps(report))
                self.assertFalse(report['execution_verified'])
                self.assertEqual(path.read_bytes(),before)
                result=self.flow.apply(plan['plan_id'],True)['results'][0]
                self.assertEqual(result['state'],'configured')
                self.assertTrue(result['preflight']['warnings'])
                updated=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(updated['hooks'][event][0]['hooks'][0],foreign)
                self.assertEqual(updated['private_setting'],'keep-me')
                preserved=self.flow.apply(self.flow.preview([client])['plan_id'],True)['results'][0]
                self.assertEqual(preserved['state'],'preserved')
                self.assertTrue(preserved['preflight']['warnings'])

    def test_plugin_preflight_does_not_claim_other_plugins_checked(self):
        with patch.dict('os.environ',{'XDG_CONFIG_HOME':str(self.home/'.config')}):
            plan=self.flow.preview(['pi','opencode'])
            for row in plan['clients']:
                self.assertEqual(row['preflight']['third_party_check'],'not_checked')
                self.assertFalse(row['preflight']['execution_verified'])
            self.assertEqual(list(self.home.iterdir()),[])

    def test_all_registered_adapters_round_trip_inside_isolated_home(self):
        from guardian.adapter_registry import supported
        with patch.dict('os.environ',{'XDG_CONFIG_HOME':str(self.home/'.config')}):
            clients=list(supported())
            plan=self.flow.preview(clients)
            self.assertEqual({row['adapter'] for row in plan['clients']},{'json-hooks','codex-hooks','opencode-plugin','pi-extension'})
            self.assertEqual(list(self.home.iterdir()),[])
            result=self.flow.apply(plan['plan_id'],True)
            self.assertTrue(all(row['state']=='configured' for row in result['results']))
            for client in clients:self.assertTrue(self.flow.operation(client,'status')['installed'])
            result=self.flow.apply(self.flow.preview(clients,'uninstall')['plan_id'],True)
            self.assertTrue(all(row['state']=='removed' for row in result['results']))
            for client in clients:self.assertFalse(self.flow.operation(client,'status')['installed'])

    def test_config_root_change_invalidates_plan_even_when_both_files_absent(self):
        with patch.dict('os.environ',{'XDG_CONFIG_HOME':str(self.home/'first')}):
            plan=self.flow.preview(['opencode'])
        with patch.dict('os.environ',{'XDG_CONFIG_HOME':str(self.home/'second')}):
            with self.assertRaises(ValueError):self.flow.apply(plan['plan_id'],True)
        self.assertFalse((self.home/'first').exists())
        self.assertFalse((self.home/'second').exists())

    def test_registry_rejects_unknown_target_instead_of_defaulting_to_gemini(self):
        with self.assertRaises(ValueError):self.flow.target('unknown-agent')
        with patch.dict('os.environ',{'XDG_CONFIG_HOME':'relative-config'}):
            with self.assertRaises(ValueError):self.flow.preview(['opencode'])

    def test_partial_hooks_repaired_without_duplicate_precheck(self):
        from guardian.integrations import command
        from scripts.install_codex_hooks import hook_command
        for client,cmd,relative in [('claude',command('claude'),'.claude/settings.json'),('codex',hook_command(),'.codex/hooks.json')]:
            with self.subTest(client=client):
                path=self.home/relative;path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps({'hooks':{'PreToolUse':[{'hooks':[{'type':'command','command':cmd}]}]}}))
                plan=self.flow.preview([client])
                self.assertIn('补齐',plan['clients'][0]['change'])
                self.assertEqual(self.flow.apply(plan['plan_id'],True)['results'][0]['state'],'configured')
                data=json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(len(data['hooks']['PreToolUse']),1)
                self.assertTrue(data['hooks']['PostToolUse'])
                self.assertFalse(self.flow.operation(client,'status')['partial'])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.flow=Onboarding(self.home)

    def test_remove_new_hooks_leaves_original_settings_without_empty_guardian_groups(self):
        for client,relative in [('claude','.claude/settings.json'),('codex','.codex/hooks.json')]:
            path=self.home/relative;path.parent.mkdir(exist_ok=True)
            original={'example_existing_setting':'preserved'}
            path.write_text(json.dumps(original))
            self.flow.apply(self.flow.preview([client])['plan_id'],True)
            self.flow.apply(self.flow.preview([client],'uninstall')['plan_id'],True)
            self.assertEqual(json.loads(path.read_text()),original)

    def test_preview_no_writes_confirm_merge_preserve_then_remove(self):
        path=self.home/'.codex/hooks.json';path.parent.mkdir()
        original={'hooks':{'PreToolUse':[{'hooks':[{'type':'command','command':'existing-orca'}]}],
                           'PostToolUse':[{'hooks':[{'type':'command','command':'existing-orca'}]}]}}
        path.write_text(json.dumps(original))
        before=path.read_bytes()
        plan=self.flow.preview(['codex'])
        self.assertEqual(path.read_bytes(),before)
        with self.assertRaises(ValueError):self.flow.apply(plan['plan_id'],False)
        result=self.flow.apply(plan['plan_id'],True)
        self.assertEqual(result['results'][0]['state'],'configured')
        self.assertFalse(result['execution_verified'])
        with self.assertRaises(ValueError):self.flow.apply(plan['plan_id'],True)
        current=path.read_bytes()
        plan=self.flow.preview(['codex'])
        self.assertEqual(self.flow.apply(plan['plan_id'],True)['results'][0]['state'],'preserved')
        self.assertEqual(path.read_bytes(),current)
        plan=self.flow.preview(['codex'],'uninstall');self.flow.apply(plan['plan_id'],True)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")),original)

    def test_all_targets_preflight_before_any_write(self):
        plan=self.flow.preview(['claude','codex'])
        path=self.home/'.codex/hooks.json';path.parent.mkdir();path.write_text('{}')
        with self.assertRaises(ValueError):self.flow.apply(plan['plan_id'],True)
        self.assertFalse((self.home/'.claude').exists())
        self.assertEqual(path.read_text(encoding="utf-8"),'{}')

    def test_expired_and_invalid_plans(self):
        plan=self.flow.preview(['codex'])
        self.flow.plans[plan['plan_id']]['expiry']=0
        with self.assertRaises(ValueError):self.flow.apply(plan['plan_id'],True)
        for clients in ([],['ollama'],['codex','codex'],['../config'],None):
            with self.assertRaises(ValueError):self.flow.preview(clients)
        self.assertEqual(list(self.home.iterdir()),[])

    def test_partial_failure_is_reported_not_fabricated_success(self):
        plan=self.flow.preview(['claude','codex'])
        original=self.flow.operation
        def operation(client,action):
            if client=='codex' and action=='install':raise OSError('fixture')
            return original(client,action)
        with patch.object(self.flow,'operation',side_effect=operation):
            result=self.flow.apply(plan['plan_id'],True)
        self.assertEqual([r['state'] for r in result['results']],['configured','failed'])
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['incomplete_clients'],['codex'])

    def test_return_without_writing_does_not_claim_success(self):
        plan=self.flow.preview(['claude'])
        original=self.flow.operation
        def operation(client,action):
            return {} if action=='install' else original(client,action)
        with patch.object(self.flow,'operation',side_effect=operation):result=self.flow.apply(plan['plan_id'],True)
        self.assertEqual(result['results'][0]['state'],'uncertain')
        self.assertEqual(result['status'],'incomplete')

    def test_exception_after_write_reports_possible_change_and_allows_fresh_preview(self):
        plan=self.flow.preview(['codex']);original=self.flow.operation
        def operation(client,action):
            result=original(client,action)
            if action=='install':raise OSError('fixture after write')
            return result
        with patch.object(self.flow,'operation',side_effect=operation):result=self.flow.apply(plan['plan_id'],True)
        self.assertEqual(result['results'][0]['state'],'uncertain')
        self.assertTrue(self.flow.operation('codex','status')['installed'])
        retry=self.flow.preview(result['incomplete_clients'])
        self.assertEqual(self.flow.apply(retry['plan_id'],True)['results'][0]['state'],'preserved')

    def test_later_client_change_during_apply_is_not_overwritten(self):
        plan=self.flow.preview(['claude','codex']);original=self.flow.operation
        def operation(client,action):
            result=original(client,action)
            if client=='claude' and action=='install':
                path=self.flow.target('codex');path.parent.mkdir();path.write_text('{"changed":true}',encoding='utf-8')
            return result
        with patch.object(self.flow,'operation',side_effect=operation):result=self.flow.apply(plan['plan_id'],True)
        self.assertEqual([r['state'] for r in result['results']],['configured','failed'])
        self.assertEqual(json.loads(self.flow.target('codex').read_text(encoding='utf-8')),{'changed':True})


if __name__=='__main__':unittest.main()
