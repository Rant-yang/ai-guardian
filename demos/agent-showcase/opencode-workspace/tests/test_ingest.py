import unittest
from shopops.ingest import load_orders,load_products
class IngestTests(unittest.TestCase):
 def test_fixtures(self):
  orders=load_orders('data/orders.csv');products=load_products('data/products.json')
  self.assertEqual(len(orders),60);self.assertEqual(len(products),4)
  self.assertIsInstance(orders[0]['quantity'],int)
  self.assertIsInstance(orders[0]['unit_price'],float)
