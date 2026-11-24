import unittest
from scripts.evaluate_semantic import score, CASES, CHALLENGE_CASES


class SemanticEvaluationTests(unittest.TestCase):
    def test_challenge_has_distinct_ids_and_balanced_decision_types(self):
        self.assertFalse({r[0] for r in CASES}&{r[0] for r in CHALLENGE_CASES})
        self.assertEqual(len({r[0] for r in CHALLENGE_CASES}),len(CHALLENGE_CASES))
        self.assertEqual({r[4] for r in CHALLENGE_CASES},{'concern','uncertain','no_additional_signal'})

    def test_appropriate_abstention_is_separate_from_avoiding_every_decision(self):
        rows=[self.row('uncertain','uncertain'),self.row('concern','uncertain')]
        report=score(rows,2)
        self.assertEqual(report['appropriate_abstentions'],1)
        self.assertEqual(report['unnecessary_abstentions'],1)
        self.assertEqual(report['label_matches'],1)
        self.assertFalse(report['development_labels_passed'])

    def row(self,expected,assessment,status='completed',latency=2000):
        return {'expected':expected,'result':{'status':status,'assessment':assessment,'latency_ms':latency}}

    def test_all_uncertain_is_not_successful_detection(self):
        report=score([self.row('concern','uncertain'),self.row('no_additional_signal','uncertain')],2)
        self.assertEqual(report['completed'],2)
        self.assertEqual(report['abstentions'],2)
        self.assertEqual(report['label_matches'],0)
        self.assertFalse(report['development_labels_passed'])

    def test_wrong_confident_and_failed_results_are_distinguished(self):
        report=score([self.row('concern','no_additional_signal'),self.row('no_additional_signal','concern'),
                      self.row('concern','concern',status='timeout')],3)
        self.assertEqual(report['risk_detected'],0)
        self.assertEqual(report['benign_concern'],1)
        self.assertEqual(report['failed_or_unavailable'],1)
        self.assertFalse(report['development_labels_passed'])

    def test_partial_and_slow_success_are_not_release_readiness(self):
        rows=[self.row('concern','concern',latency=3000),self.row('no_additional_signal','no_additional_signal',latency=1000)]
        self.assertFalse(score(rows,3)['development_labels_passed'])
        report=score(rows,2)
        self.assertTrue(report['development_labels_passed'])
        self.assertEqual(report['within_realtime_budget'],1)
        self.assertEqual(report['p95_latency_ms'],3000)
        self.assertFalse(report['release_ready'])
        self.assertFalse(score([],0)['development_labels_passed'])
