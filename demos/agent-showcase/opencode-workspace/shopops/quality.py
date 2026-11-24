VALID_STATUSES = ('paid', 'pending', 'refunded')

def validate_order(order, products):
    """Return a list of codes: unknown_product, invalid_quantity, invalid_price, invalid_status.
    Valid quantity > 0; unit_price >= 0; status in paid/pending/refunded.
    Return all applicable errors in that order.
    """
    errors = []
    if order.get('product_id') not in products:
        errors.append('unknown_product')
    quantity = order.get('quantity')
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        errors.append('invalid_quantity')
    price = order.get('unit_price')
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price < 0:
        errors.append('invalid_price')
    if order.get('status') not in VALID_STATUSES:
        errors.append('invalid_status')
    return errors
