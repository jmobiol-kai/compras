from odoo import _, models
from odoo.exceptions import UserError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def unlink(self):
        allocation_model = self.env['kai.sale.po.allocation']
        active = allocation_model.search([
            ('sale_line_id', 'in', self.ids),
            ('purchase_state', '!=', 'cancel'),
        ])
        if active:
            raise UserError(_(
                'No se puede eliminar la línea de venta: tiene cantidades '
                'comprometidas en compras que no están canceladas. Cancele '
                'esas compras para liberar la demanda.'
            ))
        # Cancelled purchases keep the link for the audit trail. The database
        # restriction would block deleting the sale line, so those historical
        # rows are removed first. The search above ran with the user's
        # companies; only those ids are removed.
        cancelled = allocation_model.search([
            ('sale_line_id', 'in', self.ids),
            ('purchase_state', '=', 'cancel'),
        ]).filtered(lambda allocation: allocation.purchase_state == 'cancel')
        if cancelled:
            # The foreign key is restrict, so the historical rows have to go
            # before the sale line. The user could already read these ids
            # (company rule applied). sudo only removes that cancelled set.
            cancelled.sudo().unlink()
        return super().unlink()
