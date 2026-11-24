# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Fill Tipo de medio on existing payments after the 19.0.1.2.0 upgrade."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    payments = env["pos.payment"].with_context(active_test=False).search([])
    payments._compute_payment_medium_type()
