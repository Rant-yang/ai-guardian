import json
import unittest
from unittest.mock import patch
from guardian.semantic import analyze


class SemanticTests(unittest.TestCase):
    def run_candidate(self,**kwargs):
        return analyze('Bash',{'command':'SYNTHETIC_PRIVATE_PARAMETER'},'synthetic task',
                       port=11435,model='fixture:local',**kwargs)

    def fake(self,port,path,body=None,timeout=3):
        if path=='/api/tags':return {'models':[{'name':'fixture:local','size':10000000,'digest':'fixture'}]}
        if path=='/api/show':return {}
        self.sent=body
        self.assertEqual(set(body['format']['required']),{'assessment','categories'})
        self.assertEqual(set(body['format']['properties']),{'assessment','categories'})
        self.assertFalse(body['format']['additionalProperties'])
        return {'message':{'content':json.dumps({'assessment':'concern','categories':['credential_access']})}}

    def test_pretool_and_advisory_schema_contracts_are_separate(self):
        from guardian.semantic import SCHEMA as pretool
        from guardian.reviewer import SCHEMA as advisory
        self.assertIsNot(pretool,advisory)
        self.assertNotIn('evidence',pretool['properties'])
        self.assertIn('evidence',advisory['required'])
        with patch('guardian.semantic.request',side_effect=self.fake):result=self.run_candidate()
        self.assertEqual(result['status'],'completed')

    def test_evidence_only_in_request_not_result_and_cpu_per_request(self):
        with patch('guardian.semantic.request',side_effect=self.fake):result=self.run_candidate()
        self.assertEqual(result['assessment'],'concern')
        self.assertTrue(result['advisory_only'])
        self.assertFalse(result['live_pretool_enabled'])
        self.assertNotIn('SYNTHETIC_PRIVATE_PARAMETER',json.dumps(result))
        self.assertIn('SYNTHETIC_PRIVATE_PARAMETER',self.sent['messages'][1]['content'])
        self.assertEqual(self.sent['options']['num_gpu'],0)

    def test_remote_invalid_and_truncated_outputs_fail_without_safe_signal(self):
        for mode in ('remote','invalid','truncated','timeout'):
            def fake(port,path,body=None,timeout=3):
                if mode=='remote' and path=='/api/show':return {'remote_host':'https://example.invalid'}
                if path=='/api/chat':
                    if mode=='timeout':raise TimeoutError('private error')
                    if mode=='invalid':return {'message':{'content':'{"assessment":"safe","categories":[]}'}}
                    if mode=='truncated':return {**self.fake(port,path,body,timeout),'done_reason':'length'}
                return self.fake(port,path,body,timeout)
            with self.subTest(mode=mode),patch('guardian.semantic.request',side_effect=fake):
                result=self.run_candidate()
                self.assertNotEqual(result['status'],'completed')
                self.assertNotIn('assessment',result)
                self.assertNotIn('private error',json.dumps(result))

    def test_input_limit_bytes_and_port_are_checked_before_network(self):
        with patch('guardian.semantic.request') as transport:
            result=analyze('Write',{'content':'文'*5000},'save',port=11435,model='fixture:local')
            self.assertEqual(result['status'],'input_too_large')
            for port in (True,80,'11435'):
                with self.assertRaises(ValueError):
                    analyze('Read',{},'read',port=port,model='fixture:local')
            transport.assert_not_called()

    def test_one_deadline_includes_metadata_requests(self):
        with patch('guardian.semantic.time.monotonic',side_effect=[0,1,10,10]),patch('guardian.semantic.request',side_effect=self.fake) as transport:
            result=self.run_candidate(timeout=5)
        self.assertEqual(result['status'],'timeout')
        self.assertEqual(transport.call_count,1)


if __name__=='__main__':unittest.main()
