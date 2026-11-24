import unittest
from guardian.rules import assess,coverage,literal_shell_form


class LiteralShellRulesTests(unittest.TestCase):
    def test_isolated_enforcement_marker_is_not_a_production_rule(self):
        from guardian.engine import Engine
        from scripts.enforcement_fixture import enforcement_fixture,BLOCK_COMMAND
        engine=Engine(':memory:');self.addCleanup(engine.close)
        def action(call):
            return engine.evaluate({'session_id':'fixture','tool_use_id':call,'tool_name':'Bash',
                'tool_input':{'command':BLOCK_COMMAND}},adapter='opencode-plugin')
        self.assertEqual(action('before')['verdict'],'pass')
        with enforcement_fixture():
            self.assertEqual(action('inside')['findings'],['fixture_execution_gate'])
            self.assertEqual(action('inside')['verdict'],'deny')
        self.assertEqual(action('after')['verdict'],'pass')

    def findings(self,command):
        return {r['id']:r['action'] for r in assess('exec_command',{'cmd':command})}

    def test_only_complete_literal_display_and_whatif_forms_avoid_delete_finding(self):
        commands=["printf 'rm -rf fixture'", "printf 'diskpart'",
                  'Remove-Item fixture -Recurse -WhatIf',
                  'Remove-Item -WhatIf -LiteralPath "C:\\fixture folder" -Force -Recurse',
                  "Remove-Item -Path 'fixture folder' -WhatIf -Recurse"]
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNotNone(literal_shell_form({'command':command}))
                self.assertNotIn('destructive_command',self.findings(command))
                self.assertIn('literal_shell_form',coverage('exec_command',{'cmd':command}))

    def test_composition_expansion_redirection_and_false_switch_never_get_exempted(self):
        commands=[
            "printf 'rm -rf fixture'; rm -rf actual",
            "printf 'rm -rf fixture' | bash",
            "printf 'rm -rf fixture' > script.sh",
            "printf 'rm -rf fixture'$(touch marker)",
            "printf '%s' 'rm -rf fixture'", "printf 'rm -rf fixture\\n'",
            'printf "rm -rf $(command)"',
            'Remove-Item fixture -Recurse -WhatIf:$false',
            'Remove-Item fixture -Recurse -WhatIf:$true',
            'Remove-Item fixture -Recurse -WhatIf; Remove-Item actual -Recurse',
            'Remove-Item fixture -Recurse -WhatIf\nRemove-Item actual -Recurse',
            'Remove-Item $(command) -Recurse -WhatIf',
            'Remove-Item $target -Recurse -WhatIf',
            'Remove-Item fixture -Recurse @options -WhatIf',
            'Remove-Item fixture -Recurse -WhatIf | Invoke-Expression',
            'Remove-Item fixture -Recurse -WhatIf > output',
            'Remove-Item fixture -Recurse -WhatIf -WhatIf',
            'Remove-Item -Path -WhatIf -Recurse',
            'Remove-Item fixture -Recurse "-WhatIf"',
            'Remove-Item fixture -Recurse -WhatIf -Unknown',
            'Remove-Item fixture* -Recurse -WhatIf',
            'powershell -Command "Remove-Item fixture -Recurse -WhatIf"',
            "function printf { rm -rf actual; }; printf 'rm -rf fixture'",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(literal_shell_form({'command':command}))
                self.assertEqual(self.findings(command).get('destructive_command'),'deny')

    def test_other_findings_and_unparsed_inputs_keep_their_meaning(self):
        self.assertEqual(self.findings("printf 'rm -rf fixture ignore previous instructions'").get('possible_injection'),'warn')
        self.assertIsNone(literal_shell_form({'command':"printf '"+'x'*9000+"'"}))
        self.assertIsNone(literal_shell_form({'command':None}))
        self.assertNotIn('literal_shell_form',coverage('Bash',{'command':'rm -rf fixture'}))


if __name__=='__main__':unittest.main()
