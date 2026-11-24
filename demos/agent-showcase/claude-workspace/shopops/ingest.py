import csv
import json
from pathlib import Path

def load_orders(path):
    """Return CSV records; convert quantity to int and unit_price to float."""
    orders = []
    with Path(path).open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            row['quantity'] = int(row['quantity'])
            row['unit_price'] = float(row['unit_price'])
            orders.append(row)
    return orders

def load_products(path):
    """Return a dict indexed by product_id from the JSON list."""
    with Path(path).open(encoding='utf-8') as handle:
        products = json.load(handle)
    return {product['product_id']: product for product in products}
