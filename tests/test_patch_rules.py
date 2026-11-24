import unittest
from guardian.rules import assess,coverage,preview,parse_patch,catalog
from guardian.engine import Engine,digest


class PatchRulesTests(unittest.TestCase):
    def test_upstream_opencode_and_codex_argument_fields(self):
        from guardian.codex_adapter import normalize
        text='*** Begin Patch\n*** Update File: .env\n@@\n-old\n+new\n*** End Patch'
        for key in ('patchText','command','input','patch'):
            self.assertIn('sensitive_file_access',self.ids({key:text}))
        normalized=normalize(dict(session_id='fixture',tool_use_id='patch',hook_event_name='PreToolUse',tool_name='apply_patch',tool_input={'command':text}))
        self.assertIn('sensitive_file_access',{r['id'] for r in assess(normalized['tool_name'],normalized['tool_input'])})
        self.assertIsNone(parse_patch({'command':text,'patchText':text}))
        previewed=preview('apply_patch',{'command':'*** Begin Patch\n*** Add File: example.md\n+https://private.example.invalid/secret\n*** End Patch'})
        self.assertEqual(previewed['targets'],['example.md'])
    def patch(self,body):return {'input':'*** Begin Patch\n'+body+'\n*** End Patch'}
    def ids(self,args):return {r['id'] for r in assess('apply_patch',args)}

    def test_sensitive_multi_targets_and_move_destination_are_checked(self):
        args=self.patch('*** Add File: notes.md\n+ordinary\n*** Update File: .env\n@@\n-old\n+new')
        self.assertIn('sensitive_file_access',self.ids(args))
        self.assertEqual(coverage('apply_patch',args)['canonical_tool'],'Edit')
        moved=self.patch('*** Update File: notes.md\n*** Move to: C:/private/.aws/credentials\n@@\n-old\n+new')
        self.assertIn('sensitive_file_access',self.ids(moved))
        self.assertEqual(preview('apply_patch',moved)['targets'],['notes.md','credentials'])
        self.assertNotIn('private',str(preview('apply_patch',moved)))

    def test_content_examples_are_not_paths_and_delete_needs_review(self):
        args=self.patch('*** Add File: docs/example.md\n+.env\n+*** Delete File: .ssh/id_rsa')
        self.assertNotIn('sensitive_file_access',self.ids(args))
        self.assertNotIn('patch_delete_review',self.ids(args))
        self.assertIn('patch_delete_review',self.ids(self.patch('*** Delete File: fixture.txt')))
        self.assertTrue({'patch_delete_review','patch_unparsed_review'}<={r['id'] for r in catalog()['rules']})

    def test_invalid_oversized_ambiguous_and_too_many_paths_are_not_silent_passes(self):
        valid=self.patch('*** Add File: example.txt\n+body')
        for args in ({'input':'bad'}, {'input':valid['input'],'patch':valid['input']},
                     self.patch('*** Add File: empty.txt'),self.patch('*** Update File: a\n*** Move to: b'),
                     self.patch('*** Add File: a\n+'+'文'*22000),
                     self.patch('\n'.join('*** Delete File: f'+str(i) for i in range(65)))):
            with self.subTest(args_length=len(str(args))):
                self.assertIsNone(parse_patch(args))
                self.assertIn('patch_unparsed_review',self.ids(args))
                self.assertEqual(coverage('apply_patch',args)['level'],'generic_only')

    def test_approval_binds_entire_original_patch_not_only_extracted_paths(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        args=self.patch('*** Delete File: fixture.txt')
        def event(identity,parameters):return engine.evaluate(dict(session_id='fixture',tool_use_id=identity,tool_name='apply_patch',tool_input=parameters),adapter='codex-hook')
        first=event('one',args);self.assertEqual(first['verdict'],'review')
        self.assertEqual(first['arguments_digest'],digest(['apply_patch',args]))
        engine.approve(first['event_id'],'approve')
        changed=event('two',self.patch('*** Delete File: different.txt'))
        self.assertEqual(changed['verdict'],'review')
        self.assertEqual(event('three',args)['verdict'],'pass')
        self.assertEqual(event('four',args)['verdict'],'review')

    def test_windows_sensitive_aliases_and_streams_still_need_review(self):
        for target in ('C:.env::$DATA','C:.env','C:/fixture/.env:secret','C:/fixture/.env::$DATA','C:/fixture/.env ',
                       'C:/fixture/.aws /credentials.','//host/share/.ssh/config:stream'):
            with self.subTest(target=target):
                args=self.patch('*** Add File: '+target+'\n+synthetic')
                self.assertIn('sensitive_file_access',self.ids(args))
                self.assertIn('sensitive_file_access',{r['id'] for r in assess('Read',{'file_path':target})})
        for target in ('C:/fixture/id_ed25519.pub:stream','C:/fixture/README.md ', 'C:/fixture/public.txt:secret'):
            self.assertNotIn('sensitive_file_access',{r['id'] for r in assess('Read',{'file_path':target})})

    def test_windows_alias_does_not_reuse_an_approval_for_original_parameters(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        def event(identity,target):return engine.evaluate(dict(session_id='fixture',tool_use_id=identity,tool_name='Read',tool_input={'file_path':target}),adapter='codex-hook')
        first=event('one','C:/fixture/.env');engine.approve(first['event_id'],'approve')
        self.assertEqual(event('two','C:/fixture/.env::$DATA')['verdict'],'review')
        self.assertEqual(event('three','C:/fixture/.env')['verdict'],'pass')
