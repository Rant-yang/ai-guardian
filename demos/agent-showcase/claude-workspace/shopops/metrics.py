def summarize(orders):
    """Input is valid orders. Return count, paid_revenue rounded to 2 decimals,
    and by_region counts. Revenue counts paid orders only.
    """
    revenue = 0.0
    by_region = {}
    for order in orders:
        region = order['region']
        by_region[region] = by_region.get(region, 0) + 1
        if order['status'] == 'paid':
            revenue += order['quantity'] * order['unit_price']
    return {
        'count': len(orders),
        'paid_revenue': round(revenue, 2),
        'by_region': by_region,
    }
