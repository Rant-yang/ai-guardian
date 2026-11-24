import unittest
from shopops.metrics import summarize
class MetricsTests(unittest.TestCase):
 def test_empty(self):
  self.assertEqual(summarize([]),{'count':0,'paid_revenue':0,'by_region':{}})
 def test_paid_only(self):
  orders=[dict(quantity=2,unit_price=12.5,status='paid',region='east'),dict(quantity=1,unit_price=90,status='refunded',region='east')]
  self.assertEqual(summarize(orders),{'count':2,'paid_revenue':25.0,'by_region':{'east':2}})
 def test_mixed_statuses(self):
  orders=[dict(quantity=1,unit_price=10,status='paid',region='east'),dict(quantity=1,unit_price=20,status='pending',region='west'),dict(quantity=1,unit_price=30,status='refunded',region='north')]
  self.assertEqual(summarize(orders),{'count':3,'paid_revenue':10.0,'by_region':{'east':1,'west':1,'north':1}})
 def test_multiple_regions(self):
  orders=[dict(quantity=2,unit_price=5,status='paid',region='east'),dict(quantity=3,unit_price=7,status='paid',region='west'),dict(quantity=1,unit_price=9,status='paid',region='east')]
  self.assertEqual(summarize(orders),{'count':3,'paid_revenue':40.0,'by_region':{'east':2,'west':1}})
 def test_revenue_rounding(self):
  orders=[dict(quantity=1,unit_price=0.1,status='paid',region='east'),dict(quantity=1,unit_price=0.2,status='paid',region='east')]
  self.assertEqual(summarize(orders)['paid_revenue'],0.3)
