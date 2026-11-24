import unittest
from guardian.rules import assess


class PythonCommandRulesTests(unittest.TestCase):
    def findings(self,command):
        return {r['id']:r['action'] for r in assess('exec_command',{'cmd':command})}

    def test_direct_and_import_alias_deletion(self):
        for code in ("import shutil; shutil.rmtree('fixture')",
                     "import shutil as fs; fs.rmtree('fixture/cache')",
                     "from shutil import rmtree as wipe; wipe(path='fixture')"):
            with self.subTest(code=code):
                self.assertEqual(self.findings('python -c "'+code+'"')['python_recursive_delete'],'deny')

    def test_printed_code_definition_and_rebinding_do_not_become_execution(self):
        commands=[
            'python -c "print(\'shutil.rmtree\')"',
            'python -c "import shutil; destroy=lambda: shutil.rmtree(\'fixture\')"',
            'python -c "import shutil; shutil=object(); shutil.rmtree(\'fixture\')"',
            'python -c "import shutil; shutil.rmtree=lambda *args: None; shutil.rmtree(\'fixture\')"',
            'python -c "from pathlib import Path as shutil; shutil.rmtree(\'fixture\')"',
            'python -c "import shutil; from fixture_module import *; shutil.rmtree(\'fixture\')"',
            'echo "import shutil; shutil.rmtree(\'fixture\')"',
        ]
        for command in commands:
            with self.subTest(command=command):self.assertNotIn('python_recursive_delete',self.findings(command))

    def test_unsupported_expansion_and_malformed_source_are_not_executed(self):
        for command in ('python -c "import shutil; shutil.rmtree(\'$TARGET\')"',
                        'python -c "import shutil; shutil.rmtree(\'fixture\')"; echo done',
                        'python -c "import shutil; not valid python!"',
                        'python -c "'+('('*10000)+'"'):
            self.assertNotIn('python_recursive_delete',self.findings(command))


if __name__=='__main__':unittest.main()
