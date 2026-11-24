import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from guardian.presentation import Presentation

class PresentationTests(unittest.TestCase):
    def test_persist_restore_and_invalid_state_hide_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'presentation.json';settings=Presentation(path)
            self.assertFalse(settings.snapshot()['privacy_mode'])
            settings.set(True);self.assertTrue(Presentation(path).snapshot()['privacy_mode'])
            for value in ('broken','null','[]','{"privacy_mode":"false"}'):
                path.write_text(value,encoding='utf-8');self.assertTrue(Presentation(path).snapshot()['privacy_mode'])
            Presentation(path).set(False);self.assertFalse(Presentation(path).snapshot()['privacy_mode'])
    def test_failed_write_preserves_current_preference_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'presentation.json';settings=Presentation(path);settings.set(True)
            with patch('guardian.presentation.os.replace',side_effect=OSError('fixture')):
                with self.assertRaises(OSError):settings.set(False)
            self.assertTrue(settings.snapshot()['privacy_mode']);self.assertTrue(Presentation(path).snapshot()['privacy_mode'])
            self.assertEqual(list(Path(folder).iterdir()),[path])
    def test_requires_boolean(self):
        settings=Presentation()
        for value in (None,0,1,'true',{}):
            with self.assertRaises(ValueError):settings.set(value)

if __name__=='__main__':unittest.main()
