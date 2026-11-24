import json
from pathlib import Path
import tempfile
import unittest
import os
import subprocess
import sys
from unittest.mock import patch
from guardian.integrations import manage, paths, command
from guardian.config_files import check_path
from types import SimpleNamespace


class GlobalIntegrationTests(unittest.TestCase):
    def test_changed_owned_hook_semantics_are_conflicts_without_overwrite(self):
        from guardian.adapter_registry import operate, target
        mutations=[lambda g,h:g.update(matcher='Read'),lambda g,h:h.update(async_=True),
                   lambda g,h:g.update(once=True),lambda g,h:h.update(type='prompt'),
                   lambda g,h:h.update(args=[]),lambda g,h:h.update(timeout=1),
                   lambda g,h:g['hooks'].append(dict(h))]
        # Use the actual JSON key, not Python's reserved async keyword.
        mutations[1]=lambda g,h:h.update({'async':True})
        for client in ('claude','gemini','qoder','codex'):
            for mutate in mutations:
                with self.subTest(client=client,mutation=mutations.index(mutate)),tempfile.TemporaryDirectory() as folder:
                    home=Path(folder);operate(client,'install',home)
                    path=target(client,home);data=json.loads(path.read_text(encoding='utf-8'))
                    event='BeforeTool' if client=='gemini' else 'PreToolUse'
                    group=data['hooks'][event][0];mutate(group,group['hooks'][0])
                    path.write_text(json.dumps(data),encoding='utf-8');before=path.read_bytes()
                    state=operate(client,'status',home)
                    self.assertTrue(state['conflict'])
                    self.assertTrue(state['configuration_issues'])
                    with self.assertRaises(ValueError):operate(client,'install',home)
                    self.assertEqual(path.read_bytes(),before)
                    from guardian.onboarding import Onboarding
                    flow=Onboarding(home)
                    with self.assertRaises(ValueError):flow.preview([client])
                    plan=flow.preview([client],'uninstall')
                    self.assertEqual(flow.apply(plan['plan_id'],True)['results'][0]['state'],'removed')
                    self.assertFalse(operate(client,'status',home)['installed'])

    def test_unrelated_conditional_hooks_do_not_reduce_guardian_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);manage('claude','install',home)
            path=paths(home,'claude');data=json.loads(path.read_text(encoding='utf-8'))
            data['hooks']['PreToolUse'].append({'matcher':'Read','hooks':[
                {'type':'command','command':'user-tool','async':True}]})
            path.write_text(json.dumps(data),encoding='utf-8')
            self.assertFalse(manage('claude','status',home)['conflict'])

    @unittest.skipUnless(os.name=='nt', 'Windows Qoder shell')
    def test_qoder_explicit_shell_handles_quoted_paths_and_missing_script(self):
        with tempfile.TemporaryDirectory(prefix="guardian ' $ test ") as folder:
            home=Path(folder)
            with patch('guardian.integrations.ROOT',home):
                manage('qoder','install',home)
                status=manage('qoder','status',home)
                self.assertTrue(status['installed'])
                self.assertFalse(status['outdated'])
                self.assertFalse(status['partial'])
                data=json.loads(paths(home,'qoder').read_text(encoding='utf-8'))
                for event in ('PreToolUse','PostToolUse','PostToolUseFailure'):
                    hook=data['hooks'][event][0]['hooks'][0]
                    self.assertEqual(hook['shell'],'powershell')
                    self.assertEqual(hook['timeout'],5)
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command('qoder')],
                                      capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout,b'')
                bash=Path('C:/Program Files/Git/bin/bash.exe')
                if bash.exists():
                    # Exercise the reported wrong-outer-shell case as well.
                    result=subprocess.run([str(bash),'--noprofile','--norc','-c',command('qoder')],capture_output=True,timeout=10)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertNotIn(b'syntax error',result.stderr)
                script=home/'guardian/hook.py';script.parent.mkdir()
                script.write_text('import json,sys\nprint(json.dumps({"input":json.load(sys.stdin)}))\n')
                for shell in ([['powershell.exe','-NoProfile','-NonInteractive','-Command']]+([[str(bash),'--noprofile','--norc','-c']] if bash.exists() else [])):
                    result=subprocess.run([*shell,command('qoder')],input=b'{"fixture":true}',capture_output=True,timeout=10)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(json.loads(result.stdout),{'input':{'fixture':True}})

    def test_qoder_legacy_upgrade_preserves_other_hooks_and_reports_shell_risk(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);path=paths(home,'qoder');path.parent.mkdir()
            foreign={'type':'command','shell':'powershell','command':"$scriptPath = Join-Path $env:USERPROFILE 'fixture.cmd'"}
            original={'hooks':{event:[{'hooks':[{'type':'command','command':command('qoder',legacy=True),'shell':'powershell' if os.name=='nt' else 'bash','timeout':5},foreign]}] for event in ('PreToolUse','PostToolUse','PostToolUseFailure')}}
            path.write_text(json.dumps(original),encoding='utf-8')
            from guardian.onboarding import Onboarding
            flow=Onboarding(home);plan=flow.preview(['qoder'])
            self.assertTrue(plan['clients'][0]['warnings'])
            result=flow.apply(plan['plan_id'],True)
            self.assertIn(result['results'][0]['state'],('configured','preserved'))
            for event,groups in json.loads(path.read_text(encoding='utf-8'))['hooks'].items():
                self.assertEqual(groups[0]['hooks'][1],foreign)
                self.assertEqual(groups[0]['hooks'][0]['command'],command('qoder'))

    def test_legacy_receipts_upgrade_in_place_without_duplicate_handlers(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);path=paths(home,'claude');path.parent.mkdir()
            events=('PreToolUse','PostToolUse','PostToolUseFailure')
            original={'hooks':{event:[{'matcher':'','hooks':[
                {'type':'command','command':command('claude',legacy=True),'timeout':5},
                {'type':'command','command':'user-hook','timeout':9}]}] for event in events}}
            path.write_text(json.dumps(original),encoding='utf-8')
            manage('claude','install',home)
            first=path.read_bytes()
            manage('claude','install',home)
            self.assertEqual(first,path.read_bytes())
            for event in events:
                groups=json.loads(first)['hooks'][event]
                self.assertEqual(len(groups),1)
                self.assertEqual([h['command'] for h in groups[0]['hooks']],
                                 [command('claude'),'user-hook'])
            self.assertFalse(manage('claude','status',home)['partial'])
            manage('claude','uninstall',home)
            for event in events:
                self.assertEqual(json.loads(path.read_bytes())['hooks'][event][0]['hooks'],
                                 [{'type':'command','command':'user-hook','timeout':9}])

    def test_reparse_parent_and_oversized_config_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'client/settings.json';path.parent.mkdir();path.write_text('{}')
            real_lstat=Path.lstat
            def lstat(entry,*args,**kwargs):
                if entry==path.parent:return SimpleNamespace(st_mode=0,st_file_attributes=1024)
                return real_lstat(entry,*args,**kwargs)
            with patch.object(Path,'lstat',autospec=True,side_effect=lstat):
                with self.assertRaises(ValueError):check_path(path)
            path.write_bytes(b' '*(2*1024*1024+1))
            with self.assertRaises(ValueError):check_path(path)

    def test_uninstall_keeps_edits_made_after_install_for_three_hook_clients(self):
        from scripts.install_codex_hooks import manage as codex_manage
        for client in ('claude','gemini','codex'):
            with self.subTest(client=client),tempfile.TemporaryDirectory() as folder:
                home=Path(folder)
                operation=(lambda action:codex_manage(home,action)) if client=='codex' else (lambda action:manage(client,action,home))
                operation('install')
                path=home/'.codex/hooks.json' if client=='codex' else paths(home,client)
                data=json.loads(path.read_text(encoding='utf-8'));data['user_added_after_install']={'model':'my-new-choice'}
                event='BeforeTool' if client=='gemini' else 'PreToolUse'
                data['hooks'][event][0]['hooks'].append({'type':'command','command':'user-added-hook','timeout':7})
                path.write_text(json.dumps(data),encoding='utf-8')
                operation('uninstall');after=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(after['user_added_after_install'],data['user_added_after_install'])
                self.assertEqual(after['hooks'][event][0]['hooks'],[{'type':'command','command':'user-added-hook','timeout':7}])
                self.assertFalse(operation('status')['installed'])

    def test_direct_installers_reject_redirected_parent_before_writing(self):
        from scripts.install_codex_hooks import manage as codex_manage
        from scripts.install_opencode import manage as plugin_manage,NAME
        for client in ('claude','gemini','codex','opencode'):
            with self.subTest(client=client),tempfile.TemporaryDirectory() as folder:
                home=Path(folder)
                path=(home/'.codex/hooks.json' if client=='codex' else home/'plugins'/NAME if client=='opencode' else paths(home,client))
                path.parent.mkdir(parents=True)
                original=b'{}';path.write_bytes(original)
                real_lstat=Path.lstat
                def lstat(entry,*args,**kwargs):
                    if entry==path.parent:return SimpleNamespace(st_mode=0,st_file_attributes=1024)
                    return real_lstat(entry,*args,**kwargs)
                with patch.object(Path,'lstat',autospec=True,side_effect=lstat):
                    with self.assertRaises(ValueError):
                        if client=='codex':codex_manage(home,'install')
                        elif client=='opencode':plugin_manage(home,'install')
                        else:manage(client,'install',home)
                self.assertEqual(path.read_bytes(),original)
                self.assertEqual(list(path.parent.iterdir()),[path])

    def test_opencode_modified_plugin_is_not_removed_and_unknown_action_never_installs(self):
        from scripts.install_opencode import manage as plugin_manage,NAME
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaises(ValueError):plugin_manage(root,'typo')
            self.assertFalse((root/'plugins').exists())
            plugin_manage(root,'install');path=root/'plugins'/NAME
            changed=path.read_text(encoding='utf-8')+'\n// user modification\n';path.write_text(changed,encoding='utf-8')
            with self.assertRaises(ValueError):plugin_manage(root,'uninstall')
            self.assertEqual(path.read_text(encoding='utf-8'),changed)

    @unittest.skipUnless(os.name=='nt' and Path('C:/Program Files/Git/bin/bash.exe').exists(), 'Windows client shells')
    def test_missing_observation_script_exits_successfully(self):
        with tempfile.TemporaryDirectory() as folder, patch('guardian.integrations.ROOT',Path(folder)):
            for client in ('claude','gemini'):
                with self.subTest(client=client):
                    args=['C:/Program Files/Git/bin/bash.exe','-c',command(client)] if client=='claude' else [os.environ['COMSPEC'],'/d','/s','/c',command(client)]
                    result=subprocess.run(args,capture_output=True,timeout=10)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(result.stdout,b'')

    def test_merge_idempotency_uninstall_preserves_other_hooks(self):
        for client,event in [('claude','PreToolUse'),('gemini','BeforeTool'),('qoder','PreToolUse')]:
            with self.subTest(client=client),tempfile.TemporaryDirectory() as folder:
                home=Path(folder);path=paths(home,client);path.parent.mkdir()
                original={'private':'sentinel','hooks':{event:[{'matcher':'*','hooks':[{'type':'command','command':'existing'}]}]}}
                path.write_text(json.dumps(original))
                manage(client,'install',home);first=path.read_bytes()
                manage(client,'install',home);self.assertEqual(first,path.read_bytes())
                self.assertTrue(manage(client,'status',home)['installed'])
                self.assertEqual(json.loads(first)['private'],'sentinel')
                manage(client,'uninstall',home)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")),original)
                self.assertTrue(list(path.parent.glob('*.guardian-backup-*')))

    def test_codex_conflict_and_preservation(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);path=paths(home,'codex');path.parent.mkdir()
            original='model = "existing"\n# preserve comment\n'
            path.write_text(original)
            manage('codex','install',home);manage('codex','install',home)
            self.assertTrue(manage('codex','status',home)['installed'])
            manage('codex','uninstall',home);self.assertEqual(path.read_text(encoding="utf-8"),original)
            path.write_text('[mcp_servers.guardian_demo]\ncommand="existing"\n')
            with self.assertRaises(ValueError):manage('codex','install',home)

    def test_invalid_json_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);path=paths(home,'claude');path.parent.mkdir();path.write_text('{broken')
            with self.assertRaises(ValueError):manage('claude','install',home)
            self.assertEqual(path.read_text(encoding="utf-8"),'{broken')

    def test_legacy_hook_migrates_once_and_preserves_empty_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);path=paths(home,'claude');path.parent.mkdir()
            path.write_text(json.dumps({'hooks':{'PreToolUse':[{'hooks':[]},{'hooks':[{'command':command('claude',legacy=True),'type':'command'}]}]}}))
            self.assertTrue(manage('claude','status',home)['outdated'])
            manage('claude','install',home)
            data=json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data['hooks']['PreToolUse']),2)
            self.assertTrue(data['hooks']['PreToolUse'][1]['hooks'][0]['command'].endswith(' || exit 0'))
            manage('claude','uninstall',home)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))['hooks']['PreToolUse'],[{'hooks':[]}])
