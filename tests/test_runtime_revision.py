import tempfile
import unittest
from pathlib import Path
from guardian.runtime_revision import source_revision


class RevisionTests(unittest.TestCase):
    def test_tracks_backend_and_rule_bytes_but_not_runtime_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'rules.json').write_text('{}');(root/'engine.py').write_text('x=1')
            first=source_revision(root)
            (root/'events.sqlite3').write_text('not inspected')
            (root/'__pycache__').mkdir();(root/'__pycache__/engine.pyc').write_bytes(b'cache')
            self.assertEqual(source_revision(root),first)
            (root/'engine.py').write_text('x=2');second=source_revision(root)
            self.assertNotEqual(first,second)
            (root/'rules.json').write_text('{"version":"changed"}')
            self.assertNotEqual(source_revision(root),second)

    def test_missing_rule_source_does_not_return_partial_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):source_revision(temp)
