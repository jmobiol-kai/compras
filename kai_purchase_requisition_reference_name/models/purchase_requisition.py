from odoo import api, models


class PurchaseRequisition(models.Model):
    _inherit = 'purchase.requisition'
    _rec_names_search = ['name', 'reference']

    @api.depends('name', 'reference')
    def _compute_display_name(self):
        for rec in self:
            if rec.reference:
                rec.display_name = f"{rec.name} - {rec.reference}"
            else:
                rec.display_name = rec.name
