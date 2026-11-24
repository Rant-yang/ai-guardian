import json
import threading
import unittest
from unittest.mock import patch
from guardian.engine import Engine
from guardian.reviewer import Reviewer
from guardian.semantic_gate import SemanticGate
from test_semantic_gate import CONFIG, action


class ModelResourceTests(unittest.TestCase):
    def setUp(self):
        self.slot=threading.BoundedSemaphore(1)
        self.engine=Engine(':memory:');self.addCleanup(self.engine.close)
        self.gate=SemanticGate(self.slot);self.addCleanup(self.gate.close)
        self.reviewer=Reviewer(self.engine,model_slot=self.slot,before_model=self.gate.invalidate_preparation)
        self.addCleanup(self.reviewer.close)
        self.event=self.engine.evaluate(action())
        self.gate.configure(CONFIG)

    def test_warmup_excludes_review_without_network_or_wait(self):
        entered=threading.Event();release=threading.Event()
        def warm(*args,**kwargs):entered.set();release.wait(3);return {'status':'completed'}
        with patch('guardian.semantic_gate.analyze',side_effect=warm),patch('guardian.reviewer.request') as transport:
            self.gate.prepare(True)
            try:
                self.assertTrue(entered.wait(1))
                self.reviewer.submit(self.event['event_id'],11435,'fixture:local',True)
                self.reviewer.jobs.join()
                result=self.engine.get_event(self.event['event_id'])['model_review']
                self.assertEqual(result['error'],'local_model_busy')
                transport.assert_not_called()
            finally:release.set();self.gate.worker.join(3)
        self.assertTrue(self.slot.acquire(blocking=False));self.slot.release()

    def test_review_invalidates_preparation_and_blocks_warmup_until_released(self):
        with patch('guardian.semantic_gate.analyze',return_value={'status':'completed'}):
            self.gate.prepare(True);self.gate.worker.join(2)
        self.assertTrue(self.gate.snapshot()['preparation']['ready'])
        entered=threading.Event();release=threading.Event()
        def transport(port,path,body=None,**kwargs):
            if path=='/api/tags':return {'models':[{'name':'fixture:local','size':10000000}]}
            if path=='/api/show':return {}
            entered.set();release.wait(3)
            return {'message':{'content':json.dumps({'assessment':'uncertain','categories':['insufficient_context']})}}
        with patch('guardian.reviewer.request',side_effect=transport):
            self.reviewer.submit(self.event['event_id'],11435,'fixture:local',True)
            try:
                self.assertTrue(entered.wait(1))
                self.assertFalse(self.gate.snapshot()['preparation']['ready'])
                self.assertEqual(self.gate.evaluate(action(),'codex-hook')['status'],'model_not_prepared')
                with self.assertRaises(ValueError):self.gate.prepare(True)
            finally:release.set();self.reviewer.jobs.join()
        self.assertTrue(self.slot.acquire(blocking=False));self.slot.release()


if __name__=='__main__':unittest.main()
