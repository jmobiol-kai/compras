from odoo import _, fields, models
from odoo.exceptions import UserError


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
    quantity = fields.Float(string='Cantidad', digits='Product Unit')
    purchase_ok = fields.Boolean(string='Se compra')

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
