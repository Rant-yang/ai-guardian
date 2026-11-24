import unittest
from guardian.desktop import recover_position


class DesktopPositionTests(unittest.TestCase):
    def test_visible_body_with_controls_above_screen_is_recovered(self):
        self.assertEqual(recover_position((100,-200,360,510),[(0,0,1920,1040)]),(100,0))
        self.assertEqual(recover_position((100,-1,360,510),[(0,0,1920,1040)]),(100,0))
        self.assertIsNone(recover_position((100,-200,360,510),[(0,-1080,1920,1080),(0,0,1920,1040)]))

    def test_visible_and_negative_monitor_positions_stay_unchanged(self):
        areas=[(-1920,0,1920,1040),(0,0,1920,1040)]
        for bounds in [(-1800,100,360,330),(100,100,360,510),(-20,200,360,330)]:
            self.assertIsNone(recover_position(bounds,areas))

    def test_removed_monitor_returns_to_nearest_available_workarea(self):
        self.assertEqual(recover_position((2100,100,360,330),[(0,0,1920,1040)]),(1560,100))
        self.assertEqual(recover_position((-1500,100,360,330),[(0,0,1920,1040)]),(0,100))

    def test_monitor_gap_does_not_count_as_visible_desktop(self):
        areas=[(-1920,0,1920,1040),(1000,0,1920,1040)]
        self.assertEqual(recover_position((300,100,360,330),areas),(-360,100))

    def test_tiny_sliver_small_workarea_and_empty_enumeration(self):
        self.assertEqual(recover_position((1900,1020,360,510),[(0,0,1920,1040)]),(1560,530))
        self.assertEqual(recover_position((2000,1000,360,510),[(10,20,200,200)]),(10,20))
        self.assertIsNone(recover_position((2000,1000,360,510),[]))
