import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from scripts.package_preview import build,verify,MANIFEST


class PreviewPackageTests(unittest.TestCase):
    def test_omitted_local_imports_fail_before_bundle_creation(self):
        for statement in ('from .helper import run','from . import helper','from guardian.helper import run','import guardian.helper','from helper import run'):
            with self.subTest(statement=statement),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/'guardian').mkdir()
                self.fixture(root,['guardian/main.py','guardian/__init__.py'])
                (root/'guardian/__init__.py').write_text('')
                (root/'guardian/main.py').write_text(statement)
                (root/'guardian/helper.py').write_text("raise RuntimeError('must not import during packaging')")
                with self.assertRaisesRegex(ValueError,'guardian/helper.py'):build(root)
                self.fixture(root,['guardian/main.py','guardian/__init__.py','guardian/helper.py'])
                content,_=build(root)
                self.assertTrue(verify(content))

    def fixture(self,root,names):
        (root/'packaging').mkdir(exist_ok=True)
        (root/MANIFEST).write_text(json.dumps([MANIFEST,*names]),encoding='utf-8')

    def test_deterministic_inventory_excludes_unlisted_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root,['README.md'])
            (root/'README.md').write_text('preview',encoding='utf-8')
            (root/'.local').mkdir();(root/'.local/access-token').write_text('PRIVATE_SENTINEL')
            first,inventory=build(root);second,_=build(root)
            self.assertEqual(first,second)
            self.assertEqual(verify(first),inventory)
            with zipfile.ZipFile(io.BytesIO(first)) as archive:
                self.assertEqual(set(archive.namelist()),{MANIFEST,'README.md','BUNDLE_MANIFEST.json'})
                for item in inventory['files']:
                    self.assertEqual(hashlib.sha256(archive.read(item['path'])).hexdigest(),item['sha256'])
                self.assertNotIn('PRIVATE_SENTINEL',b''.join(archive.read(n) for n in archive.namelist()).decode())

    def test_unsafe_missing_duplicate_and_private_paths_fail(self):
        for names in (['../outside.py'],['.local/state.json'],['artifacts/research.py'],['missing.py'],['README.md','readme.md']):
            with self.subTest(names=names),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);self.fixture(root,names)
                with self.assertRaises((ValueError,FileNotFoundError)):build(root)

    def test_real_bundle_runtime_files_and_assets_are_present(self):
        content,_=build()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for name in ('setup.ps1','guardian/server.py','guardian/semantic_gate.py','guardian/rules.json',
                         'Check.cmd','Disconnect.cmd','Feedback.cmd','TRIAL.md','trial/sample.txt',
                         'guardian/maintenance.py','scripts/maintenance.ps1','docs/maintenance.md',
                         'scripts/runtime.ps1','scripts/install_codex_hooks.py','integrations/opencode/guardian.mjs',
                         'docs/quick-start.md','docs/preview-packaging.md','docs/opencode-patch-verification.json',
                         'scripts/verify_opencode_patch.py','scripts/verify_claude_local.py','scripts/verify_codex_patch.py',
                         'docs/codex-patch-verification.json',
                         'web/app.js','web/viz.js','web/index.html'):
                self.assertIn(name,archive.namelist())

    def test_extra_or_modified_archive_content_rejected(self):
        content,_=build()
        for extra in (True,False):
            with self.subTest(extra=extra):
                stream=io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(content)) as original,zipfile.ZipFile(stream,'w') as changed:
                    for name in original.namelist():
                        changed.writestr(name,b'changed' if not extra and name=='README.md' else original.read(name))
                    if extra:changed.writestr('.local/access-token','PRIVATE')
                with self.assertRaises(ValueError):verify(stream.getvalue())


if __name__=='__main__':unittest.main()
