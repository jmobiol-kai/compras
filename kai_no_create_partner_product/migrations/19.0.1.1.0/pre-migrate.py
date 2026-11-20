"""Remember users allowed to create, before the stored boolean column is dropped.

19.0.1.0.2 cleared the legacy default. Rows that are True on a database already
at 19.0.1.0.2 were turned back on afterwards and must receive the new group.
Older databases still hold the legacy default: 19.0.1.0.2 clears those, so
this script does not promote them.
"""

import logging

_logger = logging.getLogger(__name__)

_RESET_VERSION = (19, 0, 1, 0, 2)
_TABLE = 'kai_nocreate_pp_allowed_user'


def _version_tuple(version):
    parts = []
    for part in (version or '').split('.'):
        if part.isdigit():
            parts.append(int(part))
        else:
            break
    return tuple(parts)


def migrate(cr, version):
    if not version or _version_tuple(version) < _RESET_VERSION:
        _logger.info(
            "kai_no_create_partner_product: installed version %s is older than "
            "19.0.1.0.2, leaving the legacy flag for that migration to clear.",
            version,
        )
        return
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'res_users'
           AND column_name = 'kai_allow_create_partner_product'
        """
    )
    if not cr.fetchone():
        return
    cr.execute("DROP TABLE IF EXISTS %s" % _TABLE)
    cr.execute(
        "CREATE TABLE %s (user_id integer PRIMARY KEY)" % _TABLE
    )
    cr.execute(
        """
        INSERT INTO %s (user_id)
        SELECT id
          FROM res_users
         WHERE kai_allow_create_partner_product IS TRUE
        """ % _TABLE
    )
    _logger.info(
        "kai_no_create_partner_product: remembered %s user(s) allowed to "
        "create partners and products before dropping the boolean column.",
        cr.rowcount,
    )
