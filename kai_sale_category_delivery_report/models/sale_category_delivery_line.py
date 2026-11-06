from odoo import _, fields, models
from odoo.exceptions import UserError

from ..wizard.report_rules import purchase_order_action_context

COVERAGE_SELECTION = [
    ('pending', 'Pendiente'),
    ('partial', 'Parcial'),
    ('covered', 'Cubierto'),
    ('over', 'Excedido'),
]


class KaiSaleCategoryDeliveryLine(models.TransientModel):
    _name = 'kai.sale.category.delivery.line'
    _description = 'Línea de productos por categoría y fecha de entrega'
    _order = 'categ_complete_name, product_name, id'

    wizard_id = fields.Many2one(
        'kai.sale.category.delivery.wizard',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    default_code = fields.Char(string='Referencia interna')
    product_name = fields.Char(string='Producto')
    categ_id = fields.Many2one('product.category', string='Categoría')
    categ_complete_name = fields.Char(string='Categoría')
    product_uom_id = fields.Many2one('uom.uom', string='Unidad de medida')
    qty_demand = fields.Float(string='Demanda', digits='Product Unit')
    qty_covered = fields.Float(string='Cubierto', digits='Product Unit')
    quantity = fields.Float(
        string='Pendiente',
        digits='Product Unit',
        help='Cantidad que todavía no está comprometida en una compra.',
    )
    coverage_state = fields.Selection(COVERAGE_SELECTION, string='Estado')
    purchase_ok = fields.Boolean(string='Se compra')
    sale_order_ids = fields.Many2many(
        'sale.order',
        string='Pedidos de venta',
    )
    origin_ids = fields.One2many(
        'kai.sale.category.delivery.origin',
        'line_id',
        string='Origen',
    )

    def _wizard(self):
        wizard = self.wizard_id[:1]
        if len(self.wizard_id) > 1:
            raise UserError(_('El listado mezcla más de un informe.'))
        if not wizard:
            wizard = self.env['kai.sale.category.delivery.wizard'].browse(
                self.env.context.get('wizard_id')
            ).exists()
        if not wizard:
            raise UserError(_('No se encontró el informe. Vuelva a generarlo.'))
        return wizard

    def action_create_purchase_order(self):
        return self._wizard().action_create_purchase_order()

    def action_open_origins(self):
        self.ensure_one()
        view = self.env.ref(
            'kai_sale_category_delivery_report.view_kai_sale_category_delivery_origin_list'
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Origen de %s', self.product_name or self.product_id.display_name),
            'res_model': 'kai.sale.category.delivery.origin',
            'view_mode': 'list',
            'views': [(view.id, 'list')],
            'domain': [('line_id', '=', self.id)],
            'target': 'new',
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def action_open_legacy_purchases(self):
        legacy_ids = list(self.env.context.get('legacy_purchase_ids') or [])
        if not legacy_ids:
            raise UserError(_(
                'No hay compras anteriores de esa fecha sin trazabilidad.'
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Compras anteriores sin trazabilidad'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', legacy_ids)],
            'target': 'current',
            # Same override as the generated PO: the report context is not editable.
            'context': purchase_order_action_context(),
        }


class KaiSaleCategoryDeliveryOrigin(models.TransientModel):
    _name = 'kai.sale.category.delivery.origin'
    _description = 'Pedido de venta que compone una línea del informe'
    _order = 'sale_order_name, id'

    line_id = fields.Many2one(
        'kai.sale.category.delivery.line',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Línea de venta',
        required=True,
        ondelete='cascade',
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Pedido de venta',
        required=True,
        ondelete='cascade',
    )
    sale_order_name = fields.Char(string='Pedido')
    qty_demand = fields.Float(string='Demanda', digits='Product Unit')
    qty_covered = fields.Float(string='Cubierto', digits='Product Unit')
    qty_pending = fields.Float(string='Pendiente', digits='Product Unit')
    coverage_state = fields.Selection(COVERAGE_SELECTION, string='Estado')
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unidad de medida',
        related='line_id.product_uom_id',
    )

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.sale_order_name or _('Pedido de venta'),
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': purchase_order_action_context(),
        }
