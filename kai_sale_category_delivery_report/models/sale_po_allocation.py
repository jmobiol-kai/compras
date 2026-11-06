from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class KaiSalePoAllocation(models.Model):
    """Quantity of one sale line committed by one purchase line.

    The row is the coverage. ``purchase.order.origin`` is only a label.
    Cancelled purchases keep their rows so the link stays visible, but
    ``purchase_state = cancel`` does not count. Returning the purchase to
    draft commits those quantities again. Deleting the purchase line deletes
    the rows. Deleting the sale line is refused while a non-cancelled
    purchase still points at it.
    """

    _name = 'kai.sale.po.allocation'
    _description = 'Cobertura de línea de venta por línea de compra'
    _order = 'id'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        index=True,
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Línea de venta',
        required=True,
        ondelete='restrict',
        index=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Pedido de venta',
        related='sale_line_id.order_id',
        store=True,
        index=True,
    )
    purchase_line_id = fields.Many2one(
        'purchase.order.line',
        string='Línea de compra',
        required=True,
        ondelete='cascade',
        index=True,
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Orden de compra',
        required=True,
        ondelete='cascade',
        index=True,
    )
    purchase_state = fields.Selection(
        related='purchase_order_id.state',
        string='Estado de la compra',
        store=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Producto',
        required=True,
        index=True,
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unidad de medida',
        required=True,
    )
    quantity = fields.Float(
        string='Cantidad cubierta',
        digits='Product Unit',
        required=True,
        help='Cantidad en la unidad del producto. No cuenta si la compra está cancelada.',
    )

    _sale_purchase_line_uniq = models.Constraint(
        'UNIQUE(sale_line_id, purchase_line_id)',
        'Esa línea de venta ya está vinculada a esa línea de compra.',
    )
    _quantity_positive = models.Constraint(
        'CHECK(quantity > 0)',
        'La cantidad cubierta tiene que ser mayor que cero.',
    )

    @api.model
    def lock_sale_lines(self, sale_lines):
        """Lock sale lines, then their coverage rows, in a stable order.

        Callers that also take this lock (purchase generation and purchase
        line quantity edits) must use this order so the two paths cannot
        deadlock. The lock is held until the transaction ends.
        """
        if not sale_lines:
            return
        self.env.flush_all()
        ids = tuple(sorted(set(sale_lines.ids)))
        self.env.cr.execute(
            'SELECT id FROM sale_order_line WHERE id IN %s ORDER BY id FOR UPDATE',
            (ids,),
        )
        self.env.cr.execute(
            '''SELECT id FROM kai_sale_po_allocation
               WHERE sale_line_id IN %s
               ORDER BY sale_line_id, id
               FOR UPDATE''',
            (ids,),
        )
        self.env.invalidate_all(flush=False)

    @api.constrains(
        'company_id', 'sale_line_id', 'purchase_line_id', 'purchase_order_id',
        'product_id', 'product_uom_id', 'quantity',
    )
    def _check_allocation(self):
        for rec in self:
            sale_company = rec.sale_line_id.order_id.company_id
            purchase_company = rec.purchase_line_id.order_id.company_id
            if sale_company != rec.company_id or purchase_company != rec.company_id:
                raise ValidationError(_('La cobertura no puede mezclar compañías.'))
            if rec.purchase_line_id.order_id != rec.purchase_order_id:
                raise ValidationError(_('La línea de compra no pertenece a esa orden.'))
            if rec.sale_line_id.product_id != rec.product_id:
                raise ValidationError(_(
                    'La cobertura tiene que ser del mismo producto que la línea de venta.'
                ))
            if rec.purchase_line_id.product_id != rec.product_id:
                raise ValidationError(_(
                    'La cobertura tiene que ser del mismo producto que la línea de compra.'
                ))
            if rec.product_uom_id != rec.product_id.uom_id:
                raise ValidationError(_(
                    'La cantidad cubierta se guarda en la unidad del producto.'
                ))
            rounding = rec.product_uom_id.rounding or 0.01
            if float_compare(rec.quantity, 0.0, precision_rounding=rounding) <= 0:
                raise ValidationError(_('La cantidad cubierta tiene que ser mayor que cero.'))
