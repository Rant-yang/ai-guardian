import unittest
from guardian.engine import Engine, digest
from guardian.rules import assess, shell_read_targets, preview


class ShellReadTargetsTests(unittest.TestCase):
    def test_review_preview_shows_credential_basename_without_private_path_or_command(self):
        args={'cmd':'Get-Content -LiteralPath "D:\\PRIVATE_USER\\.docker\\config.json"'}
        result=preview('exec_command',args)
        self.assertEqual(result['targets'],['config.json'])
        self.assertNotIn('PRIVATE_USER',str(result))
        self.assertNotIn('Get-Content',str(result))
        self.assertEqual(args['cmd'],'Get-Content -LiteralPath "D:\\PRIVATE_USER\\.docker\\config.json"')
        self.assertEqual(preview('Bash',{'command':"head -n 5 'private/.git-credentials'"})['targets'],['.git-credentials'])
        self.assertEqual(preview('Bash',{'command':'echo "cat private/.git-credentials"'})['targets'],[])
        self.assertEqual(preview('Bash',{'command':'cat PRIVATE_TEXT README.md'})['targets'],[])

    def test_stored_review_keeps_only_basename_and_full_argument_binding(self):
        engine=Engine(':memory:');self.addCleanup(engine.close)
        args={'cmd':'cat "D:/PRIVATE_USER/.git-credentials"'}
        event=engine.evaluate({'session_id':'fixture','tool_use_id':'read','tool_name':'exec_command','tool_input':args},adapter='codex-hook')
        self.assertEqual(event['verdict'],'review')
        self.assertEqual(event['action_preview']['targets'],['.git-credentials'])
        self.assertEqual(event['arguments_digest'],digest(['exec_command',args]))
        self.assertNotIn('PRIVATE_USER',str(engine.events()))

    def test_git_and_docker_literal_reads_and_documentation_pairs(self):
        for command in ('cat fixture/.git-credentials','cat fixture/.config/git/credentials',
                        'Get-Content -LiteralPath "C:\\fixture\\.docker\\config.json"'):
            self.assertIn('shell_sensitive_file_access',self.findings(command))
        for command in ('echo "cat fixture/.git-credentials"','cat fixture/.docker/config.json.example','cat fixture/config.json'):
            self.assertNotIn('shell_sensitive_file_access',self.findings(command))

    def findings(self,command):
        return [r['id'] for r in assess('exec_command',{'cmd':command})]

    def test_literal_sensitive_reads_across_clients_and_windows_paths(self):
        for command in ('cat fixture/.ssh/id_ed25519','Get-Content -LiteralPath "D:\\fixture space\\.env"',
                        "head -n 5 'fixture/.aws/credentials'",'type fixture\\.npmrc',
                        'cat fixture/README.md fixture/.env.local'):
            with self.subTest(command=command):self.assertIn('shell_sensitive_file_access',self.findings(command))

    def test_documentation_public_keys_and_non_read_commands_not_flagged(self):
        for command in ('echo "cat fixture/.env"','printf "cat fixture/.env"',
                        'cat fixture/id_ed25519.pub','cat fixture/README.md',
                        'cat fixture/README.md | echo fixture/.env', 'cat fixture/README.md > fixture/.env'):
            with self.subTest(command=command):self.assertNotIn('shell_sensitive_file_access',self.findings(command))

    def test_no_expansion_and_existing_destructive_rule_not_suppressed(self):
        self.assertEqual(shell_read_targets({'command':'cat "$ROOT/.env"'}),[])
        self.assertEqual(shell_read_targets({'command':'cat "unclosed'}),[])
        self.assertIn('destructive_command',self.findings('cat fixture/README.md; rm -rf fixture'))


if __name__=='__main__':unittest.main()
