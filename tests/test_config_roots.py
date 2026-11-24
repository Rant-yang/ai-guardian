import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from guardian.discovery import scan
from guardian.onboarding import Onboarding
from guardian.adapter_registry import target


class ConfigRootTests(unittest.TestCase):
    def test_scan_preview_install_and_remove_share_redirected_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            env={'PI_CODING_AGENT_DIR':str(home/'work-pi'),'QODER_CONFIG_DIR':str(home/'work-qoder'),'CLAUDE_CONFIG_DIR':str(home/'work-claude'),'CODEX_HOME':str(home/'work-codex'),'XDG_CONFIG_HOME':str(home/'work-xdg')}
            original={'custom':'preserved'}
            for client in ('claude','codex','qoder'):
                path=target(client,home,env);path.parent.mkdir();path.write_text(json.dumps(original))
            model=home/'work-codex/config.toml';model.write_text('model="keep"')
            with patch.dict('os.environ',env):
                rows={row['id']:row for row in scan(home,env,lambda _:None)['clients']}
                flow=Onboarding(home);plan=flow.preview(['claude','codex','opencode','qoder','pi'])
                for item in plan['clients']:
                    self.assertEqual(item['configuration_scope'],rows[item['id']]['configuration_scopes'][0])
                result=flow.apply(plan['plan_id'],True)
                self.assertTrue(all(row['state']=='configured' for row in result['results']))
                result=flow.apply(flow.preview(['claude','codex','opencode','qoder','pi'],'uninstall')['plan_id'],True)
                self.assertTrue(all(row['state']=='removed' for row in result['results']))
                for client in ('claude','codex','qoder'):self.assertEqual(json.loads(flow.target(client).read_text()),original)
            self.assertEqual(model.read_text(),'model="keep"')
            for name in ('.claude','.codex','.config','.qoder'):self.assertFalse((home/name).exists())

    def test_bad_override_disables_selection_and_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            for client,key in [('pi','PI_CODING_AGENT_DIR'),('qoder','QODER_CONFIG_DIR'),('claude','CLAUDE_CONFIG_DIR'),('codex','CODEX_HOME'),('opencode','XDG_CONFIG_HOME')]:
                with patch.dict('os.environ',{key:'relative-path'}):
                    row=next(row for row in scan(home,{key:'relative-path'},lambda _:None)['clients'] if row['id']==client)
                    self.assertFalse(row['integration_available'])
                    self.assertEqual(row['integration_state'],'config_error')
                    with self.assertRaises(ValueError):Onboarding(home).preview([client])
            self.assertEqual(list(home.iterdir()),[])

    def test_changed_override_requires_new_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            for client,key in [('pi','PI_CODING_AGENT_DIR'),('qoder','QODER_CONFIG_DIR'),('claude','CLAUDE_CONFIG_DIR'),('codex','CODEX_HOME')]:
                flow=Onboarding(home)
                with patch.dict('os.environ',{key:str(home/'first')}):plan=flow.preview([client])
                with patch.dict('os.environ',{key:str(home/'second')}):
                    with self.assertRaises(ValueError):flow.apply(plan['plan_id'],True)
            self.assertEqual(list(home.iterdir()),[])


if __name__=='__main__':unittest.main()
