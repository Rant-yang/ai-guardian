import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from guardian.connections import Connections
from scripts.install_opencode import manage, NAME


class PresenceTests(unittest.TestCase):
    def test_revision_is_bounded_and_legacy_presence_is_not_current(self):
        registry=Connections()
        data=dict(instance_id=str(uuid.uuid4()),adapter='opencode-plugin',mode='observe',project_id='a'*16)
        registry.heartbeat(data);self.assertFalse(registry.snapshot()[0]['revision_current'])
        registry.heartbeat({**data,'adapter_revision':'scope-4'})
        self.assertTrue(registry.snapshot()[0]['revision_current'])
        for revision in ('x'*41,'<script>',42):
            with self.assertRaises(ValueError):registry.heartbeat({**data,'adapter_revision':revision})
        self.assertTrue(registry.snapshot()[0]['revision_current'])

    def test_expiry_and_reregistration(self):
        registry = Connections()
        data = dict(instance_id=str(uuid.uuid4()),adapter='opencode-plugin',mode='observe',project_id='a'*16)
        with patch('guardian.connections.time.time',return_value=100):
            registry.heartbeat(data)
            self.assertTrue(registry.snapshot()[0]['online'])
        with patch('guardian.connections.time.time',return_value=146):
            self.assertFalse(registry.snapshot()[0]['online'])
            registry.heartbeat(data)
            self.assertTrue(registry.snapshot()[0]['online'])
        self.assertEqual(len(registry.snapshot()),1)

    def test_installer_preserves_others_and_refuses_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'opencode.json').write_text('PRIVATE_CONFIG_SENTINEL')
            manage(root,'install')
            manage(root,'install')
            self.assertTrue(manage(root,'status')['installed'])
            self.assertEqual((root/'opencode.json').read_text(),'PRIVATE_CONFIG_SENTINEL')
            target=root/'plugins'/NAME
            original=target.read_text()
            target.write_text('unrelated plugin')
            for action in ('install','uninstall'):
                with self.assertRaises(ValueError): manage(root,action)
            target.write_text(original)
            manage(root,'uninstall')
            self.assertFalse(target.exists())
            self.assertTrue((root/'opencode.json').exists())

    def test_capacity_evicts_stale_not_active(self):
        registry=Connections()
        with patch('guardian.connections.time.time',return_value=100):
            for _ in range(256):registry.heartbeat(dict(instance_id=str(uuid.uuid4()),adapter='opencode-plugin',mode='observe',project_id='b'*16))
            with self.assertRaises(ValueError):registry.heartbeat(dict(instance_id=str(uuid.uuid4()),adapter='opencode-plugin',mode='observe',project_id='b'*16))
        with patch('guardian.connections.time.time',return_value=150):
            registry.heartbeat(dict(instance_id=str(uuid.uuid4()),adapter='opencode-plugin',mode='observe',project_id='b'*16))
            self.assertEqual(len(registry.snapshot()),256)
            self.assertEqual(sum(row['online'] for row in registry.snapshot()),1)
