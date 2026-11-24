# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging

from . import models
from . import wizard

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Fill stored report fields on existing pos.payment rows."""
    payments = env["pos.payment"].with_context(active_test=False).search([])
    _logger.info(
        "kai_pos_payment_report: recomputing report fields on %s payments",
        len(payments),
    )
    payments._compute_sales_journal_id()
    payments._compute_payment_date_date()
    payments._compute_payment_medium_type()
    _logger.info("kai_pos_payment_report: recompute done")
