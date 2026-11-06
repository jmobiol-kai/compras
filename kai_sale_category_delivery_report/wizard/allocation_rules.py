"""Coverage of sale lines by purchase lines.

Pure functions: no ORM. Quantities are in the product UoM.

Policy
------
* Coverage is the sum of allocation quantities whose purchase order is not
  cancelled. Draft, sent, to approve and purchase all count. Cancel releases
  the demand but the rows stay, so setting the PO back to draft commits the
  same quantities again.
* Pending is computed per sale line (demand minus covered, never below
  zero). An over-covered line does not cover a sibling line, and it does
  not block buying the sibling's pending quantity.
* A purchase order that has no allocation rows does not cover anything.
  Legacy orders are not matched by origin text.
* Lowering a purchase line quantity reduces allocations from the newest
  link backward, down to the quantity still ordered. Raising it does not
  invent coverage. Changing the product drops the links.
"""
import math


def units(qty, rounding):
    """Half-up count of ``rounding`` steps in ``qty``."""
    rounding = rounding or 0.01
    if rounding <= 0:
        rounding = 0.01
    scaled = float(qty or 0.0) / rounding
    if scaled >= 0:
        return int(math.floor(scaled + 0.5))
    return int(math.ceil(scaled - 0.5))


def covering_state(state):
    """Every purchase state except cancel commits the linked quantity."""
    return bool(state) and state != 'cancel'


def covered_map(allocation_rows):
    """Sum covering quantities by sale line.

    ``allocation_rows`` is an iterable of ``(sale_line_id, quantity, state)``.
    Rows without a sale line, and cancelled (or empty) states, add nothing.
    A purchase order that is not listed here covers nothing.
    """
    totals = {}
    for sale_line_id, quantity, state in allocation_rows:
        if not sale_line_id or not covering_state(state):
            continue
        totals[sale_line_id] = totals.get(sale_line_id, 0.0) + float(quantity or 0.0)
    return totals


def line_state(demand_units, covered_units, pending_units):
    if pending_units > 0 and covered_units > 0:
        return 'partial'
    if pending_units > 0:
        return 'pending'
    if covered_units > demand_units:
        return 'over'
    if covered_units > 0:
        return 'covered'
    return 'pending'


def same_company(company_ids, expected):
    """True when every non-empty company is the active one."""
    return all(company_id == expected for company_id in company_ids if company_id)


def aggregate_report(origins, covered):
    """Group sale-line snapshots by product.

    ``origins`` items need ``sale_line_id``, ``sale_order_id``, ``product_id``
    and ``qty_demand``. ``covered`` maps sale line id to quantity already
    committed. Lines with neither demand nor coverage are omitted. Pending
    of one line is never reduced by surplus coverage on another line.
    """
    products = {}
    order = []
    sequenced = sorted(
        origins,
        key=lambda item: (item.get('sale_order_id') or 0, item.get('sale_line_id') or 0),
    )
    for origin in sequenced:
        rounding = origin.get('rounding') or 0.01
        demand_u = units(origin.get('qty_demand'), rounding)
        covered_u = units(covered.get(origin.get('sale_line_id'), 0.0), rounding)
        if demand_u <= 0 and covered_u <= 0:
            continue
        pending_u = max(0, demand_u - covered_u)
        product_id = origin['product_id']
        if product_id not in products:
            products[product_id] = {
                'product_id': product_id,
                'rounding': rounding,
                'purchase_ok': bool(origin.get('purchase_ok')),
                'default_code': origin.get('default_code') or '',
                'product_name': origin.get('product_name') or '',
                'categ_id': origin.get('categ_id'),
                'categ_complete_name': origin.get('categ_complete_name') or '',
                'product_uom_id': origin.get('product_uom_id'),
                'origins': [],
                'demand_u': 0,
                'covered_u': 0,
                'pending_u': 0,
            }
            order.append(product_id)
        bucket = products[product_id]
        bucket['origins'].append({
            'sale_line_id': origin['sale_line_id'],
            'sale_order_id': origin.get('sale_order_id'),
            'sale_order_name': origin.get('sale_order_name') or '',
            'qty_demand': demand_u * rounding,
            'qty_covered': covered_u * rounding,
            'qty_pending': pending_u * rounding,
            'coverage_state': line_state(demand_u, covered_u, pending_u),
        })
        bucket['demand_u'] += demand_u
        bucket['covered_u'] += covered_u
        bucket['pending_u'] += pending_u
    rows = []
    for product_id in order:
        bucket = products[product_id]
        rounding = bucket['rounding']
        bucket['qty_demand'] = bucket['demand_u'] * rounding
        bucket['qty_covered'] = bucket['covered_u'] * rounding
        bucket['qty_pending'] = bucket['pending_u'] * rounding
        bucket['coverage_state'] = line_state(
            bucket['demand_u'], bucket['covered_u'], bucket['pending_u'],
        )
        bucket['sale_order_ids'] = list(dict.fromkeys(
            item['sale_order_id'] for item in bucket['origins'] if item['sale_order_id']
        ))
        rows.append(bucket)
    return rows


def plan_purchase(origins, covered):
    """What a new purchase order may commit, and the report rows.

    ``reason`` is ``empty`` (no demand), ``covered`` (nothing pending),
    ``not_purchasable`` (pending exists but no product can be bought) or
    ``None`` when ``purchases`` is not empty. Cancelled coverage must already
    be absent from ``covered``.
    """
    rows = aggregate_report(origins, covered)
    purchases = []
    skipped = []
    for row in rows:
        if row['pending_u'] <= 0:
            continue
        if not row['purchase_ok']:
            skipped.append(row['product_name'] or str(row['product_id']))
            continue
        purchases.append({
            'product_id': row['product_id'],
            'quantity': row['qty_pending'],
            'rounding': row['rounding'],
            'product_name': row['product_name'],
            'allocations': [
                {
                    'sale_line_id': origin['sale_line_id'],
                    'sale_order_id': origin['sale_order_id'],
                    'quantity': origin['qty_pending'],
                }
                for origin in row['origins']
                if origin['qty_pending'] > 0
            ],
        })
    if not rows:
        reason = 'empty'
    elif not purchases and skipped:
        reason = 'not_purchasable'
    elif not purchases:
        reason = 'covered'
    else:
        reason = None
    return {
        'rows': rows,
        'purchases': purchases,
        'skipped': skipped,
        'reason': reason,
    }


def cap_allocation_quantities(quantities, cap, rounding=0.01):
    """Fit ``quantities`` under ``cap`` by shrinking the newest links first.

    A larger cap does not increase any quantity: extra purchased units are
    not treated as coverage. A cap of zero clears every link. The result
    keeps the original length; zeros mean the link should be removed.
    """
    rounding = rounding or 0.01
    cap_units = max(0, units(cap, rounding))
    current = [max(0, units(qty, rounding)) for qty in quantities]
    overflow = sum(current) - cap_units
    if overflow > 0:
        for index in range(len(current) - 1, -1, -1):
            if overflow <= 0:
                break
            take = min(current[index], overflow)
            current[index] -= take
            overflow -= take
    return [value * rounding for value in current]
