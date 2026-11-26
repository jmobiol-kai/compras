# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import models

# Fields that can change the fallback journal when the order is not invoiced
# yet. Some come from msb_pos_facturacion_lotes and may be absent.
_KAI_JOURNAL_TRIGGER_FIELDS = frozenset({
    "account_move",
    "use_batch_journal",
    "batch_invoice_journal_id",
    "config_id",
})


class PosOrder(models.Model):
    _inherit = "pos.order"

    def write(self, vals):
        res = super().write(vals)
        if _KAI_JOURNAL_TRIGGER_FIELDS & set(vals):
            self.mapped("payment_ids")._compute_sales_journal_id()
        return res
