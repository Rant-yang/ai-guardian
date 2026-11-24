def summarize(orders):
    """Input is valid orders. Return count, paid_revenue rounded to 2 decimals,
    and by_region counts. Revenue counts paid orders only.
    """
    paid_revenue = sum(order['quantity'] * order['unit_price']
                       for order in orders if order['status'] == 'paid')
    by_region = {}
    for order in orders:
        region = order['region']
        by_region[region] = by_region.get(region, 0) + 1
    return {
        'count': len(orders),
        'paid_revenue': round(paid_revenue, 2),
        'by_region': by_region,
    }
