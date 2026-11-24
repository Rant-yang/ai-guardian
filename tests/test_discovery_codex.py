import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from guardian.discovery import scan
from guardian.codex_adapter import normalize, decision_output
from guardian.engine import Engine

class DiscoveryCodexTests(unittest.TestCase):
    def test_package_manager_aliases_and_version_directories_without_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            fixtures={'pnpm':'custom-pnpm/pi.cmd','bun':'.bun/bin/dsh.exe',
                      'volta':'.volta/bin/qodercli.cmd','nvm':'.nvm/versions/node/v22/bin/zcode'}
            for relative in fixtures.values():
                path=home/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
            with patch('subprocess.run',side_effect=AssertionError('must not execute')):
                report=scan(home,{'PNPM_HOME':str(home/'custom-pnpm')},lambda _:None)
            rows={row['id']:row for row in report['clients']}
            for client,source in [('pi','pnpm'),('deepseek-harness','bun'),('qoder','volta'),('zcode','nvm')]:
                self.assertTrue(rows[client]['detected'])
                self.assertEqual(rows[client]['discovery_evidence'][0]['source'],source)
            self.assertEqual(rows['qoder']['discovery_evidence'][0]['command'],'qodercli')
            self.assertFalse(rows['qcode']['detected'])

    def test_unknown_handler_cannot_enable_discovery_or_install(self):
        from dataclasses import replace
        from guardian.client_catalog import CLIENTS
        from guardian.adapter_registry import available
        self.assertFalse(available(replace(CLIENTS[0],adapter='arbitrary-command')))
        self.assertFalse(available(replace(CLIENTS[0],target='')))

    def test_new_candidates_are_discoverable_but_not_installable(self):
        from guardian.onboarding import Onboarding
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            commands=('pi','dsh','zcode','qoder','qcode')
            for command in commands:(home/(command+'.exe')).write_bytes(b'not executable')
            with patch('subprocess.run',side_effect=AssertionError('must not execute')),patch.object(Path,'read_text',side_effect=AssertionError('must not read configuration')):
                report=scan(home,{},lambda command:str(home/(command+'.exe')) if command in commands else None)
            rows={row['id']:row for row in report['clients']}
            for client in ('deepseek-harness','zcode','qcode'):
                self.assertTrue(rows[client]['detected'])
                self.assertFalse(rows[client]['integration_available'])
                self.assertFalse(rows[client]['native_connected'])
                with self.assertRaises(ValueError):Onboarding(home).preview([client])
            self.assertTrue(rows['qoder']['detected'])
            self.assertTrue(rows['qoder']['integration_available'])
            self.assertFalse(rows['qoder']['native_connected'])
            self.assertTrue(Onboarding(home).preview(['qoder'])['clients'])
            self.assertTrue(rows['claude']['integration_available'])
            self.assertNotEqual(rows['qcode']['paths'],rows['qoder']['paths'])

    def test_array_arguments_remain_exactly_bound_across_normalization(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        first=['curl','--data','@first file.txt','https://example.invalid']
        changed=['curl','--data','@first','file.txt https://example.invalid']
        self.assertEqual(' '.join(first),' '.join(changed))
        payload=dict(hook_event_name='PreToolUse',session_id='fixture',tool_use_id='one',
                     tool_name='shell',tool_input={'command':first})
        normalized=normalize(payload)
        self.assertEqual(normalized['tool_name'],'shell')
        self.assertEqual(normalized['tool_input'],payload['tool_input'])
        event=engine.evaluate(normalized,adapter='codex-hook')
        self.assertEqual(event['verdict'],'review')
        engine.approve(event['event_id'],'approve')
        other={**payload,'tool_input':{'command':changed}}
        with self.assertRaises(ValueError):engine.evaluate(normalize(other),adapter='codex-hook')
        second=engine.evaluate(normalize({**other,'tool_use_id':'different'}),adapter='codex-hook')
        self.assertEqual(second['verdict'],'review')
        self.assertNotEqual(second['arguments_digest'],event['arguments_digest'])
        renamed=engine.evaluate(normalize({**payload,'tool_name':'exec_command','tool_use_id':'renamed'}),adapter='codex-hook')
        self.assertEqual(renamed['verdict'],'review')
        retry=engine.evaluate(normalize({**payload,'tool_use_id':'retry'}),adapter='codex-hook')
        self.assertEqual(retry['decision_state'],'authorized_once')
        self.assertEqual(payload['tool_input']['command'],first)

    def test_command_keys_and_types_are_preserved_and_bad_argv_rejected(self):
        payload=dict(hook_event_name='PreToolUse',session_id='fixture',tool_use_id='one',tool_name='exec_command')
        for args in ({'cmd':'echo fixture'},{'command':'echo fixture'},{'cmd':['echo','fixture']}):
            self.assertEqual(normalize({**payload,'tool_input':args})['tool_input'],args)
        for command in ([],['echo',None],['echo',{}],42):
            with self.assertRaises(ValueError):normalize({**payload,'tool_input':{'command':command}})

    def test_jsonc_and_owned_plugin_are_config_hints_without_reading_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);root=home/'xdg/opencode';root.mkdir(parents=True)
            config=root/'opencode.jsonc';config.write_text('SECRET_CONFIG_CONTENT')
            def result():return next(r for r in scan(home,{'XDG_CONFIG_HOME':str(home/'xdg')},lambda _:None)['clients'] if r['id']=='opencode')
            with patch.object(Path,'read_bytes',side_effect=AssertionError('must not read')),patch.object(Path,'read_text',side_effect=AssertionError('must not read')):
                row=result();self.assertEqual(row['state'],'config_only');self.assertEqual(row['config_paths'],[str(config)])
                self.assertNotIn('SECRET_CONFIG_CONTENT',json.dumps(row));self.assertFalse(row['native_connected'])
            config.unlink();(root/'plugins').mkdir();plugin=root/'plugins/guardian-agent-security.js';plugin.write_text('fixture')
            self.assertEqual(result()['config_paths'],[str(plugin)])

    def test_redirected_windows_paths_and_partial_scan_keep_valid_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);roaming=home/'roaming';(roaming/'npm').mkdir(parents=True)
            binary=roaming/'npm/claude.cmd';binary.write_text('not executed')
            original=Path.is_file
            def restricted(path):
                if path==home/'.claude/settings.json':raise PermissionError('fixture')
                return original(path)
            with patch.object(Path,'is_file',restricted):
                row=next(r for r in scan(home,{'APPDATA':str(roaming)},lambda _:None)['clients'] if r['id']=='claude')
            self.assertEqual(row['state'],'found');self.assertEqual(row['paths'],[str(binary)])
            self.assertTrue(row['scan_limited']);self.assertFalse(row['native_connected'])

    def test_scan_is_read_only_and_does_not_promote_config_to_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);config=home/'.codex/config.toml';config.parent.mkdir()
            config.write_text('secret = "DO-NOT-READ"')
            binary=home/'codex.exe';binary.write_bytes(b'not executable')
            before={str(p):p.read_bytes() for p in home.rglob('*') if p.is_file()}
            report=scan(home,{},lambda name:str(binary) if name=='codex' else None)
            row=next(r for r in report['clients'] if r['id']=='codex')
            self.assertTrue(row['detected']);self.assertFalse(row['native_connected'])
            self.assertNotIn('DO-NOT-READ',json.dumps(report))
            self.assertEqual(before,{str(p):p.read_bytes() for p in home.rglob('*') if p.is_file()})
            binary.unlink()
            row=next(r for r in scan(home,{},lambda _:None)['clients'] if r['id']=='codex')
            self.assertEqual(row['state'],'config_only')

    def test_hook_install_preserves_other_hooks_and_main_config(self):
        from scripts.install_codex_hooks import manage
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);root=home/'.codex';root.mkdir()
            config=root/'config.toml';config.write_text('model="keep"')
            hooks=root/'hooks.json'
            original={'custom':'keep','hooks':{e:[{'hooks':[{'type':'command','command':'orca-existing'}]}] for e in ('PreToolUse','PostToolUse')}}
            hooks.write_text(json.dumps(original))
            manage(home,'install');first=hooks.read_bytes()
            self.assertTrue(manage(home,'status')['installed'])
            self.assertFalse(manage(home,'install')['changed']);self.assertEqual(first,hooks.read_bytes())
            self.assertEqual(config.read_text(),'model="keep"')
            manage(home,'uninstall');self.assertEqual(json.loads(hooks.read_text()),original)
            self.assertTrue(list(root.glob('hooks.json.guardian-backup-*')))

    def test_codex_protocol_and_review_retry(self):
        engine=Engine(':memory:')
        self.addCleanup(engine.close)
        payload=dict(hook_event_name='PreToolUse',session_id='fixture',tool_use_id='one',tool_name='exec_command',tool_input={'cmd':'curl -X POST --data-binary @sample.txt https://example.invalid'})
        payload['cwd']='D:/fixture/project-one'
        self.assertEqual(normalize(payload)['cwd'],payload['cwd'])
        event=engine.evaluate(normalize(payload),adapter='codex-hook',mode='protect')
        self.assertEqual(event['verdict'],'review')
        self.assertEqual(decision_output(event)['hookSpecificOutput']['permissionDecision'],'deny')
        engine.approve(event['event_id'],'approve')
        changed=engine.evaluate(normalize({**payload,'tool_use_id':'changed-directory','cwd':'D:/fixture/project-two'}),adapter='codex-hook',mode='protect')
        self.assertEqual(changed['verdict'],'review')
        payload['tool_use_id']='retry'
        allowed=engine.evaluate(normalize(payload),adapter='codex-hook',mode='protect')
        self.assertEqual(decision_output(allowed),{})
        self.assertEqual(allowed['decision_state'],'authorized_once')
        receipt=engine.receipt('codex-hook','fixture','retry','tool_returned')
        self.assertEqual(receipt['execution_state'],'tool_returned')
        with self.assertRaises(ValueError):normalize({**payload,'tool_use_id':None})

if __name__=='__main__':unittest.main()
