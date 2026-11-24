"""Runtime discovery without modifying the host PATH or launcher registrations."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='nt','Windows runtime selection')
class RuntimeTests(unittest.TestCase):
    def probe(self, listing):
        with tempfile.TemporaryDirectory(prefix='guardian-runtime-') as temp:
            root=Path(temp)
            def quote(value):return "'"+str(value).replace("'","''")+"'"
            launcher=root/'fake-launcher.ps1'
            launcher.write_text("if($args.Count -ne 1 -or $args[0] -ne '-0p'){throw 'Only listing allowed'}\n"+
                                '\n'.join('Write-Output '+quote(line) for line in listing)+
                                '\n$global:LASTEXITCODE=0\n',encoding='utf-8-sig')
            script=root/'probe.ps1'
            script.write_text("$ErrorActionPreference='Stop'\n. "+quote(ROOT/'scripts/runtime.ps1')+
                '\nfunction Get-Command { param($Name,[switch]$All,$ErrorAction) '+
                "if($Name -eq 'py.exe'){[pscustomobject]@{Source="+quote(launcher)+"}} }\n"+
                'Get-GuardianPython -ProjectRoot '+quote(root)+'\n',encoding='utf-8-sig')
            return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],
                                  capture_output=True,timeout=20)

    def test_launcher_only_runtime_with_legacy_and_current_listing(self):
        for tag in ('-V:3.11','-3.11-64'):
            with self.subTest(tag=tag):
                result=self.probe([f' {tag} * {sys.executable}'])
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stdout.decode().strip(),sys.executable)

    def test_unsupported_missing_and_malformed_entries_are_not_used(self):
        result=self.probe([f' -V:3.14 * {sys.executable}',
                           r' -V:3.11 C:\guardian-fixture-nonexistent\python.exe',
                           f' arbitrary command {sys.executable}',
                           f' -V:3.11 {sys.executable} ; injected'])
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'was not found on PATH or in Python Launcher',result.stderr)

    def test_empty_launcher_does_not_request_or_install_runtime(self):
        result=self.probe([])
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'Existing files were preserved',result.stderr)
