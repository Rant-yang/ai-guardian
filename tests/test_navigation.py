import unittest
import uuid
import time
from guardian.navigation import Navigation


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.nav=Navigation();self.instance=str(uuid.uuid4());self.other=str(uuid.uuid4())
        self.event={'event_id':'event','source_adapter':'opencode-plugin','is_demo':False}
        self.nav.remember(self.event,'ses_fixture1234',self.instance)
    def heartbeat(self,instance=None):
        return self.nav.heartbeat({'instance_id':instance or self.instance,'navigation':'session_select'})
    def test_navigation_is_bound_single_delivery_and_ack_not_visual_proof(self):
        self.heartbeat();result=self.nav.request('event')
        self.assertEqual(result['state'],'queued');self.assertNotIn('session_id',result)
        self.assertEqual(self.heartbeat(self.other),{})
        instruction=self.heartbeat()['navigation']
        self.assertEqual(instruction['session_id'],'ses_fixture1234')
        self.assertEqual(self.heartbeat(),{})
        with self.assertRaises(ValueError):self.nav.acknowledge({'request_id':instruction['request_id'],'instance_id':self.other,'status':'dispatched'})
        self.nav.acknowledge({'request_id':instruction['request_id'],'instance_id':self.instance,'status':'dispatched'})
        status=self.nav.status('event');self.assertTrue(status['requested']);self.assertFalse(status['visible_session_verified'])
    def test_unregistered_expired_and_cleared_events_never_navigate(self):
        self.assertIsNone(self.nav.request('event'))
        self.heartbeat();result=self.nav.request('event');self.nav.requests[result['request_id']]['expires']=time.monotonic()-1
        self.assertEqual(self.nav.status('event')['state'],'expired');self.assertEqual(self.heartbeat(),{})
        self.nav.forget(['event']);self.assertIsNone(self.nav.request('event'));self.assertIsNone(self.nav.status('event'))
    def test_duplicate_report_cannot_redirect_to_other_instance(self):
        self.nav.remember(self.event,'ses_other5678',self.other)
        self.heartbeat();self.heartbeat(self.other);self.nav.request('event')
        self.assertEqual(self.heartbeat(self.other),{})
        self.assertEqual(self.heartbeat()['navigation']['session_id'],'ses_fixture1234')

    def test_new_click_replaces_queued_session_instead_of_building_navigation_backlog(self):
        self.heartbeat();first=self.nav.request('event')
        other={**self.event,'event_id':'new-event'}
        self.nav.remember(other,'ses_newsession123',self.instance)
        self.nav.request('new-event')
        self.assertEqual(self.nav.status('event')['state'],'superseded')
        self.assertEqual(self.heartbeat()['navigation']['session_id'],'ses_newsession123')
        with self.assertRaises(ValueError):self.nav.acknowledge({'request_id':first['request_id'],'instance_id':self.instance,'status':'dispatched'})
    def test_demo_and_invalid_session_or_instance_are_ignored(self):
        for event,session,instance in [({**self.event,'event_id':'demo','is_demo':True},'ses_fixture1234',self.instance),
            ({**self.event,'event_id':'invalid'},'https://example.invalid',self.instance),
            ({**self.event,'event_id':'invalid'},'ses_fixture1234','wrong')]:
            self.nav.remember(event,session,instance)
            self.assertNotIn(event['event_id'],self.nav.origins)
