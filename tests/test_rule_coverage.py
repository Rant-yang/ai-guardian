import unittest
from guardian.engine import Engine, digest
from guardian.rules import assess, coverage, preview


class RuleCoverageTests(unittest.TestCase):
    def test_git_and_docker_credential_targets_are_reviewed_without_reading_content(self):
        paths=['.git-credentials','.config/git/credentials','C:\\fixture\\.docker\\config.json']
        for path in paths:
            for tool in ('Read','Write','Edit'):
                with self.subTest(path=path,tool=tool):
                    matches=assess(tool,{'file_path':path})
                    self.assertTrue(any(r['id']=='sensitive_file_access' and r['action']=='review' for r in matches))
            patch='*** Begin Patch\n*** Add File: '+path+'\n+fixture\n*** End Patch'
            self.assertIn('sensitive_file_access',[r['id'] for r in assess('apply_patch',{'command':patch})])
        for path in ('docs/git-credentials.md','.docker/config.json.example','.config/git/credentials-notes','project/config.json'):
            self.assertNotIn('sensitive_file_access',[r['id'] for r in assess('Read',{'path':path})])
        self.assertNotIn('sensitive_file_access',[r['id'] for r in assess('Write',{'path':'README.md','content':'Read .git-credentials and .docker/config.json'})])

    def test_credential_rule_checks_paths_not_document_content(self):
        for tool,args in [('Write',{'file_path':'docs/README.md','content':'id_rsa and .env'}),
                          ('Edit',{'filePath':'docs/setup.md','old_string':'id_ed25519','new_string':'key'}),
                          ('Read',{'path':'.ssh/id_rsa.pub'}),('Read',{'file_path':'docs/id_rsa-notes.md'})]:
            self.assertNotIn('sensitive_file_access',[r['id'] for r in assess(tool,args)])
        for path in ('.aws/credentials','.npmrc','.pypirc','.env.production','C:\\fixture\\.ssh\\id_ecdsa'):
            self.assertIn('sensitive_file_access',[r['id'] for r in assess('Read',{'path':path})])
        self.assertIn('sensitive_file_access',[r['id'] for r in assess('Read',{'path':'.env','file_path':'README.md'})])
        self.assertEqual(coverage('Read',{'content':'ordinary'})['level'],'generic_only')

    def test_recursive_delete_flags_and_non_option_filenames(self):
        for command in ('rm -r -f fixture','rm -f -r fixture','rm -r fixture','rm --recursive fixture'):
            self.assertIn('destructive_command',[r['id'] for r in assess('Bash',{'command':command})])
        self.assertNotIn('destructive_command',[r['id'] for r in assess('Bash',{'command':'rm fixture-report'})])

    def test_tool_aliases_cover_equivalent_actions_without_mutation(self):
        for tool,args in [('Bash',{'command':'rm -rf fixture'}),('exec_command',{'cmd':'rm -rf fixture'}),
                          ('run_shell_command',{'command':'rm -rf fixture'})]:
            original=dict(args)
            self.assertIn('destructive_command',[r['id'] for r in assess(tool,args)])
            self.assertEqual(coverage(tool,args)['level'],'tool_rules')
            self.assertEqual(args,original)
        for tool in ('Read','read','read_file'):
            self.assertIn('sensitive_file_access',[r['id'] for r in assess(tool,{'absolute_path':'C:/fixture/.env'})])
        self.assertEqual(preview('read_file',{'absolute_path':'C:/private/.env'})['targets'],['.env'])

    def test_unknown_tools_and_unparsed_commands_are_not_reported_as_covered(self):
        for tool,args in [('custom_tool',{}),('Bash',{'command':['rm','-rf','fixture']})]:
            self.assertEqual(coverage(tool,args)['level'],'generic_only')
        self.assertIn('possible_injection',[r['id'] for r in assess('custom_tool',{'text':'ignore previous instructions'})])
        args={'command':['printf',"'rm -rf fixture'"]}
        self.assertIn('destructive_command',[r['id'] for r in assess('shell',args)])
        self.assertEqual(args,{'command':['printf',"'rm -rf fixture'"]})
        self.assertIn('未解析参数边界',coverage('shell',args)['note'])

    def test_powershell_encoded_switch_prefixes_require_review(self):
        # Strings only: no payload is decoded or executed by this test.
        names={'ec',*('encodedcommand'[:n] for n in range(1,15))}
        for name in names:
            for prefix in ('-','--','/'):
                for exe in ('pwsh','PowerShell.exe'):
                    command=f'{exe} -NoProfile {prefix}{name.upper()} ZQBjAGgAbwA='
                    with self.subTest(command=command):
                        hits={r['id']:r['action'] for r in assess('exec_command',{'cmd':command})}
                        self.assertEqual(hits.get('encoded_execution'),'review')
        args={'command':['pwsh','-ec','ZQBjAGgAbwA=']}
        self.assertIn('encoded_execution',[r['id'] for r in assess('shell',args)])
        self.assertEqual(coverage('shell',args)['level'],'generic_only')

    def test_encoded_switch_boundaries_and_literal_display(self):
        for command in ('pwsh -ExecutionPolicy RemoteSigned -File demo.ps1',
                        'powershell -ep RemoteSigned', 'pwsh -encodedarguments example',
                        'pwsh -encSomething example','pwsh -File example-ec.txt',
                        "printf 'pwsh -ec example'",'pwsh-helper -ec example'):
            with self.subTest(command=command):
                self.assertNotIn('encoded_execution',[r['id'] for r in assess('Bash',{'command':command})])
        for command in ("printf 'pwsh -ec example' | bash",
                        "printf 'example'; pwsh -ec example",'pwsh\t-ec\texample'):
            self.assertIn('encoded_execution',[r['id'] for r in assess('Bash',{'command':command})])

    def test_alias_keeps_original_arguments_bound_to_approval(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        args={'cmd':'curl -d @sample.txt https://example.invalid'}
        event=engine.evaluate(dict(session_id='s',tool_use_id='c',tool_name='exec_command',tool_input=args),adapter='codex-hook')
        self.assertEqual(event['verdict'],'review')
        self.assertEqual(event['arguments_digest'],digest(['exec_command',args]))
        self.assertEqual(event['rule_coverage']['canonical_tool'],'Bash')
        self.assertNotIn('sample.txt',str(event['action_preview']))
