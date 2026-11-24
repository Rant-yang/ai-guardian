import csv, json, collections
rows = list(csv.DictReader(open('data/orders.csv', newline='', encoding='utf-8')))
prods = {p['product_id'] for p in json.load(open('data/products.json', encoding='utf-8'))}
merged = collections.Counter()
bad = []
for r in rows:
    q = int(r['quantity']); p = float(r['unit_price']); s = r['status']
    if r['product_id'] not in prods or q <= 0 or p < 0 or s not in ('paid','pending','refunded'):
        bad.append(r['order_id'])
        continue
    merged[r['region']] += 1
print('rows', len(rows), 'bad', len(bad), bad)
print('regions', dict(sorted(merged.items())))
rev = sum(int(r['quantity'])*float(r['unit_price']) for r in rows if r['status']=='paid' and r['product_id'] in prods and int(r['quantity'])>0 and float(r['unit_price'])>=0)
print('paid_revenue', round(rev,2))
