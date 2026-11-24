"""python -m shopops.cli --data data --output output"""
import argparse
import json
from pathlib import Path
from .ingest import load_orders, load_products
from .quality import validate_order
from .metrics import summarize
from .reporting import save_reports

def main(argv=None):
    # Implement --data/--output, filter invalid orders, write reports plus rejected.json.
    parser = argparse.ArgumentParser(description='Build the ShopOps operations report.')
    parser.add_argument('--data', default='data', help='directory containing orders.csv and products.json')
    parser.add_argument('--output', default='output', help='directory for generated reports')
    args = parser.parse_args(argv)

    data_dir = Path(args.data)
    output_dir = Path(args.output)

    orders = load_orders(data_dir / 'orders.csv')
    products = load_products(data_dir / 'products.json')

    valid_orders = []
    rejected = []
    for order in orders:
        errors = validate_order(order, products)
        if errors:
            rejected.append({'order_id': order['order_id'], 'errors': errors})
        else:
            valid_orders.append(order)

    summary = summarize(valid_orders)
    save_reports(summary, output_dir)
    (output_dir / 'rejected.json').write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    print('Processed {} orders: {} valid, {} rejected'.format(
        len(orders), len(valid_orders), len(rejected)))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
