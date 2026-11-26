"""Pure rules for the category / delivery-date sales report.

Kept free of the ORM so the calendar window and the sale-state filter can be
checked without a database. Odoo stores ``commitment_date`` as naive UTC.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FALLBACK_TZ = 'America/Argentina/Buenos_Aires'

# Odoo 19's selection is draft / sent / sale / cancel, and a locked order stays
# ``sale``. ``done`` stays in the domain so a database that still has that value
# (historical rows, or a customization) is not dropped. Quotations and
# cancellations are never included.
CONFIRMED_STATES = ('sale', 'done')
QUOTE_STATES = ('draft', 'sent')


def resolve_tz_name(user_tz, company_tz):
    """User timezone, then the company partner timezone, then Argentina."""
    return user_tz or company_tz or FALLBACK_TZ


def timezone(tz_name):
    name = tz_name or FALLBACK_TZ
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo(FALLBACK_TZ)


def commitment_utc_window(day, tz_name):
    """Half-open ``[start, end)`` naive UTC datetimes for ``day`` in ``tz_name``.

    An order is included when its ``commitment_date`` falls on that calendar
    day in the report timezone, not on the UTC date.
    """
    tz = timezone(tz_name)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    utc = ZoneInfo('UTC')
    start_utc = start_local.astimezone(utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(utc).replace(tzinfo=None)
    return start_utc, end_utc


def sale_states(include_quotes=False):
    """Confirmed orders only (``sale`` and ``done``).

    Draft and sent quotations are never included. ``include_quotes`` is
    accepted so an older caller still works, and it does not change the
    result: a stored wizard flag cannot put presupuestos into the domain.
    """
    return CONFIRMED_STATES


# Odoo 19 web client, action_service.js ``doActionButton``: context keys that
# are NOT copied from the current action onto the action a button returns.
_CONTEXT_NOT_FORWARDED = (
    'active_id',
    'active_ids',
    'group_by',
    'orderedBy',
)


def _context_key_is_forwarded(key):
    if key in _CONTEXT_NOT_FORWARDED or key.endswith('_view_ref'):
        return False
    return not (
        key.startswith('default_')
        or key.startswith('search_default_')
        or key.startswith('show_')
    )


def purchase_order_action_context():
    """Flags applied last on the generated purchase-order form.

    The report action sets ``create`` / ``edit`` / ``delete`` to false so the
    product list cannot be edited in place. Odoo 19 copies those keys onto
    the action returned by «Generar orden de compra». ``formView`` then opens
    an existing record read-only (``activeActions.edit === false`` and a
    ``resId``), which blocks ``partner_ref`` and the purchase journal together
    with the rest of the form. Forcing the three flags true restores the
    standard purchase form. It does not change field ``readonly`` on confirmed
    or locked orders, and it does not touch ``allowed_company_ids``.
    """
    return {
        'create': True,
        'edit': True,
        'delete': True,
    }


def merged_button_action_context(parent_context, action_context):
    """Context Odoo 19 builds for an object-button action.

    Mirrors ``doActionButton``: forward the current action context except
    ``default_*``, ``search_default_*``, ``show_*``, ``*_view_ref``,
    ``group_by``, ``active_id`` and ``active_ids``, then let the action
    context override. Used so the edit-flag fix can be checked without the
    web client.
    """
    merged = {
        key: value
        for key, value in (parent_context or {}).items()
        if _context_key_is_forwarded(key)
    }
    merged.update(action_context or {})
    return merged
