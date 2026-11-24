import csv
import json
from pathlib import Path

def load_orders(path):
    """Return CSV records; convert quantity to int and unit_price to float."""
    with open(Path(path), newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        orders = []
        for row in reader:
            orders.append({
                'order_id': row['order_id'],
                'product_id': row['product_id'],
                'quantity': int(row['quantity']),
                'unit_price': float(row['unit_price']),
                'status': row['status'],
                'region': row['region'],
            })
    return orders

def load_products(path):
    """Return a dict indexed by product_id from the JSON list."""
    with open(Path(path), encoding='utf-8') as handle:
        items = json.load(handle)
    return {item['product_id']: item for item in items}
