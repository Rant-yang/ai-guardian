"""python -m shopops.cli --data data --output output"""
import argparse
import json
from pathlib import Path
from .ingest import load_orders, load_products
from .quality import validate_order
from .metrics import summarize
from .reporting import save_reports

def main():
    # Implement --data/--output, filter invalid orders, write reports plus rejected.json.
    parser = argparse.ArgumentParser(description='ShopOps order quality report')
    parser.add_argument('--data', default='data', help='directory with orders.csv and products.json')
    parser.add_argument('--output', default='output', help='directory for generated reports')
    args = parser.parse_args()

    data_dir = Path(args.data)
    orders = load_orders(data_dir / 'orders.csv')
    products = load_products(data_dir / 'products.json')

    valid = []
    rejected = []
    for order in orders:
        errors = validate_order(order, products)
        if errors:
            rejected.append({'order_id': order['order_id'], 'errors': errors})
        else:
            valid.append(order)

    summary = summarize(valid)
    output_dir = Path(args.output)
    save_reports(summary, output_dir)
    (output_dir / 'rejected.json').write_text(
        json.dumps(rejected, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )

    print('orders={} valid={} rejected={} paid_revenue={:.2f}'.format(
        len(orders), summary['count'], len(rejected), summary['paid_revenue']
    ))

if __name__ == '__main__':
    main()
