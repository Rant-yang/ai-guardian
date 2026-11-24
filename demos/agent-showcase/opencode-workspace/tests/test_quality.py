import unittest
from shopops.quality import validate_order
class QualityTests(unittest.TestCase):
 def test_valid(self):
  self.assertEqual(validate_order(dict(product_id='p1',quantity=1,unit_price=0,status='paid'),{'p1':{}}),[])
 def test_all_errors(self):
  self.assertEqual(validate_order(dict(product_id='missing',quantity=0,unit_price=-1,status='oops'),{}),['unknown_product','invalid_quantity','invalid_price','invalid_status'])
 def test_unknown_product(self):
  self.assertEqual(validate_order(dict(product_id='missing',quantity=1,unit_price=10,status='paid'),{'p1':{}}),['unknown_product'])
 def test_negative_price(self):
  self.assertEqual(validate_order(dict(product_id='p1',quantity=1,unit_price=-0.01,status='paid'),{'p1':{}}),['invalid_price'])
 def test_invalid_status(self):
  self.assertEqual(validate_order(dict(product_id='p1',quantity=1,unit_price=5,status='cancelled'),{'p1':{}}),['invalid_status'])
 def test_zero_quantity(self):
  self.assertEqual(validate_order(dict(product_id='p1',quantity=0,unit_price=5,status='paid'),{'p1':{}}),['invalid_quantity'])
