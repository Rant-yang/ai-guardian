import json
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch
from guardian.onboarding import Onboarding
from guardian.adapter_registry import target,operate


class PiInstallTests(unittest.TestCase):
    def test_missing_extension_loader_blocks_only_in_protection(self):
        from scripts.install_pi import extension_text
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'.local').mkdir()
            with patch('scripts.install_pi.ROOT',root):loader=extension_text()
            path=root/'loader.mjs';path.write_text(loader,encoding='utf-8')
            code='import loader from '+json.dumps(path.as_uri())+';const handlers={};await loader({on:(name,fn)=>handlers[name]=fn});console.log(JSON.stringify(await handlers.tool_call()||{}));'
            for mode in ('observe','protect',''):
                (root/'.local/runtime-modes.json').write_text(json.dumps({'pi-extension':mode}))
                result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout).get('block',False),mode!='observe')

    def test_preview_install_remove_leaves_settings_and_other_extensions_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);destination=target('pi',home)
            destination.parent.mkdir(parents=True)
            settings=destination.parent.parent/'settings.json';settings.write_text('{"model":"keep"}')
            other=destination.parent/'other.js';other.write_text('user extension')
            flow=Onboarding(home);plan=flow.preview(['pi'])
            self.assertFalse(destination.exists())
            self.assertEqual(flow.apply(plan['plan_id'],True)['results'][0]['state'],'configured')
            before=destination.read_bytes();operate('pi','install',home);self.assertEqual(destination.read_bytes(),before)
            self.assertEqual(flow.apply(flow.preview(['pi'],'uninstall')['plan_id'],True)['results'][0]['state'],'removed')
            self.assertEqual(json.loads(settings.read_text()),{'model':'keep'})
            self.assertEqual(other.read_text(),'user extension')

    def test_modified_loader_is_never_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);operate('pi','install',home);path=target('pi',home)
            path.write_bytes(path.read_bytes()+b'\n// user modified\n');before=path.read_bytes()
            self.assertTrue(operate('pi','status',home)['conflict'])
            for action in ('install','uninstall'):
                with self.assertRaises(ValueError):operate('pi',action,home)
                self.assertEqual(path.read_bytes(),before)
