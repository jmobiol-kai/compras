# -*- coding: utf-8 -*-
from odoo import models
from odoo.tools import float_compare


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        res = super().write(vals)
        if 'standard_price' in vals:
            self._kai_sync_requisition_line_prices()
        return res

    def _kai_sync_requisition_line_prices(self):
        """Keep open purchase agreement lines aligned with accounting cost."""
        Line = self.env['purchase.requisition.line']
        precision = self.env['decimal.precision'].precision_get('Product Price')
        for product in self:
            lines = Line.search([
                ('product_id', '=', product.id),
                ('requisition_id.state', 'not in', ('cancel', 'done')),
            ])
            for line in lines:
                cost = product.with_company(line.company_id).standard_price
                if float_compare(line.price_unit, cost, precision_digits=precision) != 0:
                    line.write({'price_unit': cost})
