"""Pure rules for the category / delivery-date sales report.

Kept free of the ORM so the calendar window and the vendor suggestion can be
checked without a database. Odoo stores ``commitment_date`` as naive UTC.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FALLBACK_TZ = 'America/Argentina/Buenos_Aires'

# Odoo 19's selection is draft / sent / sale / cancel, and a locked order stays
# ``sale``. ``done`` stays in the domain so a database that still has that value
# (historical rows, or a customization) is not dropped.
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


def sale_states(include_quotes):
    """Confirmed orders, plus draft and sent when the user asks for quotes."""
    if include_quotes:
        return CONFIRMED_STATES + QUOTE_STATES
    return CONFIRMED_STATES


def shared_preferred_partner_id(preferred_partner_ids):
    """Partner id when every purchasable product has that same preferred seller.

    ``None`` (or another falsy id) means that product has no seller. An empty
    sequence means there is nothing to buy, so nothing is suggested.
    """
    partner_ids = list(preferred_partner_ids)
    if not partner_ids or any(not partner_id for partner_id in partner_ids):
        return None
    first = partner_ids[0]
    if all(partner_id == first for partner_id in partner_ids):
        return first
    return None
