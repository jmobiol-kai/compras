"""Clear the commercial-create flag after the default changed to False.

Until 19.0.1.0.1 the field defaulted to True, and that value is stored on
``res_users``. Changing the Python default does not rewrite existing rows,
so an upgrade would leave every current user allowed to create contacts and
products from sales orders, purchase orders, invoices, and payments.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        ALTER TABLE res_users
        ALTER COLUMN kai_allow_create_partner_product SET DEFAULT FALSE
        """
    )
    cr.execute(
        """
        UPDATE res_users
           SET kai_allow_create_partner_product = FALSE
         WHERE kai_allow_create_partner_product IS DISTINCT FROM FALSE
        """
    )
    _logger.info(
        "kai_no_create_partner_product: upgrade from %s cleared "
        "kai_allow_create_partner_product on %s user(s).",
        version,
        cr.rowcount,
    )
