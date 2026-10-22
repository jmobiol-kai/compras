#### models/purchase_order.py
from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.onchange('journal_id')
    def _onchange_journal_id_currency(self):
        """Forzar la moneda de la orden de compra según la moneda del diario"""
        if self.journal_id and self.journal_id.currency_id:
            self.currency_id = self.journal_id.currency_id
