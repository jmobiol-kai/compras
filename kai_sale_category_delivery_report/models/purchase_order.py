from odoo import _, api, fields, models
from odoo.tools.float_utils import float_compare, float_is_zero

from ..wizard.allocation_rules import cap_allocation_quantities
from ..wizard.report_rules import purchase_order_action_context


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    kai_allocation_ids = fields.One2many(
        'kai.sale.po.allocation',
        'purchase_order_id',
        string='Cobertura de ventas',
        copy=False,
    )
    kai_sale_order_count = fields.Integer(
        string='Ventas origen',
        compute='_compute_kai_sale_order_count',
    )

    @api.depends('kai_allocation_ids.sale_order_id')
    def _compute_kai_sale_order_count(self):
        for order in self:
            order.kai_sale_order_count = len(order.kai_allocation_ids.sale_order_id)

    def action_view_kai_source_sales(self):
        self.ensure_one()
        orders = self.kai_allocation_ids.sale_order_id
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Ventas origen'),
            'res_model': 'sale.order',
            'domain': [('id', 'in', orders.ids)],
            'target': 'current',
            # The report list is not editable. Opening a sale from here must
            # not inherit that flag; the sale form keeps its own readonly.
            'context': purchase_order_action_context(),
        }
        if len(orders) == 1:
            action.update({
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_id': orders.id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')],
            })
        return action


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    kai_allocation_ids = fields.One2many(
        'kai.sale.po.allocation',
        'purchase_line_id',
        string='Cobertura de ventas',
        copy=False,
    )

    def write(self, vals):
        tracked = {'product_id', 'product_qty', 'product_uom_id'} & set(vals)
        if not tracked:
            return super().write(vals)
        products_before = {line.id: line.product_id.id for line in self}
        res = super().write(vals)
        self._kai_sync_allocations(products_before)
        return res

    def _kai_sync_allocations(self, products_before):
        """Keep links equal to what this line still buys.

        A smaller quantity, or a unit that converts to less, drops coverage
        from the newest sale line backward. A larger quantity does not cover
        more sale demand. A different product drops the links; the demand
        becomes pending again and this line is no longer tied to those sales.
        """
        allocs = self.kai_allocation_ids
        if not allocs:
            return
        Allocation = self.env['kai.sale.po.allocation']
        Allocation.lock_sale_lines(allocs.sale_line_id)
        for line in self:
            line_allocs = line.kai_allocation_ids.sorted(key=lambda alloc: alloc.id)
            if not line_allocs:
                continue
            product_changed = products_before.get(line.id) != line.product_id.id
            linked_products = line_allocs.product_id
            if product_changed or linked_products != line.product_id:
                line_allocs.unlink()
                continue
            cap = line.product_uom_id._compute_quantity(
                line.product_qty,
                line.product_id.uom_id,
                rounding_method='HALF-UP',
            )
            rounding = line.product_id.uom_id.rounding or 0.01
            new_quantities = cap_allocation_quantities(
                [alloc.quantity for alloc in line_allocs], cap, rounding,
            )
            to_unlink = Allocation.browse()
            for alloc, quantity in zip(line_allocs, new_quantities):
                if float_is_zero(quantity, precision_rounding=rounding):
                    to_unlink |= alloc
                elif float_compare(alloc.quantity, quantity, precision_rounding=rounding) != 0:
                    alloc.quantity = quantity
            to_unlink.unlink()
