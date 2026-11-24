import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from guardian import adapter_registry
from guardian.maintenance import inspect,prepare_disconnect,disconnect,export_report
from guardian.onboarding import Onboarding


class MaintenanceTests(unittest.TestCase):
    def test_support_export_projects_only_allowed_fields_and_never_overwrites(self):
        rows=[dict(id='claude',configuration='attention',command='PRIVATE_TOKEN',
                   path='PRIVATE_PATH',warnings=['PRIVATE_WARNING'])]
        with patch('guardian.maintenance.inspect',return_value=rows):
            first=export_report(self.home,self.home)
            second=export_report(self.home,self.home)
        self.assertNotEqual(first,second)
        raw=first.read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE_',raw)
        report=json.loads(raw)
        self.assertEqual(report['clients'],[{'id':'claude','configuration':'attention'}])
        self.assertFalse(report['execution_verified'])
        self.assertTrue(first.is_relative_to(self.home/'.local/support'))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        env={s.config_root_env:str(self.home/s.config_root_default)
             for s in adapter_registry.SPECS.values() if s.config_root_env}
        self.env=patch.dict('os.environ',env);self.env.start();self.addCleanup(self.env.stop)
        self.flow=Onboarding(self.home)

    def test_inspection_and_preview_do_not_create_configuration(self):
        self.assertEqual(len(inspect(self.home)),6)
        plans,blocked=prepare_disconnect(self.flow)
        self.assertEqual(len(plans),6);self.assertFalse(blocked)
        self.assertEqual(list(self.home.iterdir()),[])

    def test_disconnect_all_adapters_preserves_foreign_hooks_and_settings(self):
        target=self.flow.target('claude');target.parent.mkdir(parents=True)
        original={'setting':'keep','hooks':{'PreToolUse':[{'hooks':[{'type':'command','command':'foreign-hook'}]}]}}
        target.write_text(json.dumps(original),encoding='utf-8')
        clients=list(adapter_registry.supported())
        self.flow.apply(self.flow.preview(clients)['plan_id'],True)
        plans,blocked=prepare_disconnect(self.flow)
        self.assertFalse(blocked)
        self.assertTrue(all(r['state']=='removed' for r in disconnect(self.flow,plans)))
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')),original)
        self.assertTrue(all(not self.flow.operation(c,'status')['installed'] for c in clients))

    def test_conflict_is_reported_without_preventing_other_removals(self):
        target=self.flow.target('pi');target.parent.mkdir(parents=True)
        target.write_text('CUSTOM_PRIVATE_PLUGIN',encoding='utf-8')
        self.flow.apply(self.flow.preview(['claude'])['plan_id'],True)
        plans,blocked=prepare_disconnect(self.flow)
        self.assertEqual(blocked,['pi'])
        results=disconnect(self.flow,plans)
        self.assertEqual(next(r for r in results if r['id']=='claude')['state'],'removed')
        self.assertEqual(target.read_text(),'CUSTOM_PRIVATE_PLUGIN')
        self.assertNotIn('CUSTOM_PRIVATE_PLUGIN',json.dumps(inspect(self.home)))

    def test_changed_configuration_after_preview_is_not_removed(self):
        self.flow.apply(self.flow.preview(['claude'])['plan_id'],True)
        plans,_=prepare_disconnect(self.flow)
        path=self.flow.target('claude');updated=json.loads(path.read_text(encoding='utf-8'))
        updated['new_setting']='preserve';path.write_text(json.dumps(updated),encoding='utf-8')
        before=path.read_bytes();results=disconnect(self.flow,plans)
        self.assertEqual(next(r for r in results if r['id']=='claude')['state'],'failed')
        self.assertEqual(path.read_bytes(),before)
