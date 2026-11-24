import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from guardian.installation_binding import resolve_binding
from guardian.installation_identity import identity
from guardian.connections import Connections
from guardian.onboarding import Onboarding
from scripts.install_opencode import manage,plugin_text,NAME


class BindingTests(unittest.TestCase):
    def test_configured_loaded_changed_removed_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);config=home/'.config/opencode';target=config/'plugins'/NAME
            with patch.dict('os.environ',{'XDG_CONFIG_HOME':str(home/'.config')}):
                manage(config,'install')
                installation=identity('opencode',target)
                resolver=lambda client,scope,revision:resolve_binding(client,scope,revision,home)
                payload=dict(instance_id=str(uuid.uuid4()),adapter='opencode-plugin',mode='observe',project_id='a'*16,
                             installation_id=installation,loader_revision='scope-1',adapter_revision='scope-4')
                for registry in (Connections(resolver),Connections(resolver)):
                    registry.heartbeat(payload)
                    self.assertEqual(registry.snapshot()[0]['installation_binding'],'matched_local_configuration')
                with self.assertRaises(ValueError):registry.heartbeat({**payload,'installation_id':'b'*32})
                original=target.read_bytes();target.write_text('unrelated')
                registry.heartbeat(payload)
                self.assertEqual(registry.snapshot()[0]['installation_binding'],'configuration_changed')
                target.write_bytes(original);manage(config,'uninstall');registry.heartbeat(payload)
                self.assertEqual(registry.snapshot()[0]['installation_binding'],'configuration_removed')
                self.assertEqual(resolver('opencode',None,None),'not_reported')
                self.assertEqual(resolver('opencode','b'*32,'scope-1'),'different_configuration')

    def test_legacy_upgrade_is_previewed_backed_up_and_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);config=home/'.config/opencode';target=config/'plugins'/NAME
            target.parent.mkdir(parents=True);target.write_text(plugin_text(),encoding='utf-8')
            before=target.read_bytes()
            with patch.dict('os.environ',{'XDG_CONFIG_HOME':str(home/'.config')}):
                flow=Onboarding(home)
                plan=flow.preview(['opencode'])
                self.assertEqual(target.read_bytes(),before)
                self.assertIn('补齐',plan['clients'][0]['change'])
                self.assertEqual(flow.apply(plan['plan_id'],True)['results'][0]['state'],'configured')
                self.assertFalse(manage(config,'status')['partial'])
                self.assertIn('installation_id',target.read_text())
                self.assertTrue(list(target.parent.glob(NAME+'.guardian-backup-*')))
                manage(config,'uninstall');self.assertFalse(target.exists())

    def test_modified_legacy_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory);target=config/'plugins'/NAME
            target.parent.mkdir();target.write_text(plugin_text()+'// user customization')
            before=target.read_bytes()
            for action in ('install','uninstall'):
                with self.assertRaises(ValueError):manage(config,action)
            self.assertEqual(target.read_bytes(),before)


if __name__=='__main__':unittest.main()
