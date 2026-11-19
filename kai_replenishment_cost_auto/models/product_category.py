from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProductCategory(models.Model):
    _inherit = 'product.category'

    kai_margin_defined = fields.Boolean(
        string='Definir margen',
        help=(
            'Si está desmarcado, el margen y el recargo se heredan de la '
            'categoría padre. En la raíz, sin definir, el margen es 0.'
        ),
    )
    kai_margin_percent = fields.Float(
        string='Margen %',
        digits='Discount',
        help='Margen de ganancia de esta categoría. Se usa si «Definir margen» está marcado.',
    )
    kai_surcharge = fields.Float(
        string='Recargo',
        digits='Product Price',
        help='Recargo fijo que se suma después del margen. Se usa si «Definir margen» está marcado.',
    )
    kai_effective_margin_percent = fields.Float(
        string='Margen efectivo %',
        digits='Discount',
        compute='_compute_kai_effective_margin',
        store=True,
        recursive=True,
    )
    kai_effective_surcharge = fields.Float(
        string='Recargo efectivo',
        digits='Product Price',
        compute='_compute_kai_effective_margin',
        store=True,
        recursive=True,
    )

    @api.depends(
        'kai_margin_defined',
        'kai_margin_percent',
        'kai_surcharge',
        'parent_id.kai_effective_margin_percent',
        'parent_id.kai_effective_surcharge',
    )
    def _compute_kai_effective_margin(self):
        for category in self:
            if category.kai_margin_defined or not category.parent_id:
                category.kai_effective_margin_percent = (
                    category.kai_margin_percent if category.kai_margin_defined else 0.0
                )
                category.kai_effective_surcharge = (
                    category.kai_surcharge if category.kai_margin_defined else 0.0
                )
            else:
                category.kai_effective_margin_percent = category.parent_id.kai_effective_margin_percent
                category.kai_effective_surcharge = category.parent_id.kai_effective_surcharge

    def write(self, vals):
        res = super().write(vals)
        watched = {'kai_margin_defined', 'kai_margin_percent', 'kai_surcharge', 'parent_id'}
        if watched.intersection(vals):
            self._kai_reprice_products_using_category_margin()
        return res

    def _kai_reprice_products_using_category_margin(self):
        """Recalcula el precio de venta de quienes usan este margen.

        Incluye las hijas que heredan y los fabricados (LdM) que ya están
        en «Por margen». No toca productos con margen propio.
        """
        categories = self.search([('id', 'child_of', self.ids)])
        products = self.env['product.template'].search([
            ('categ_id', 'in', categories.ids),
            ('list_price_type', '=', 'by_margin'),
            ('kai_own_margin', '=', False),
        ])
        products._kai_update_planned_prices_from_replenishment()
        return products

    def action_kai_apply_margin(self):
        """Pasa a «Por margen» los productos sin override y recalcula el precio."""
        products = self._kai_apply_margin_to_products()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Margen aplicado'),
                'message': _('Se actualizaron %s productos.', len(products)),
                'type': 'success',
                'sticky': False,
            },
        }

    def _kai_apply_margin_to_products(self):
        categories = self.search([('id', 'child_of', self.ids)])
        products = self.env['product.template'].search([
            ('categ_id', 'in', categories.ids),
            ('kai_own_margin', '=', False),
        ])
        to_switch = products.filtered(lambda product: product.list_price_type != 'by_margin')
        if to_switch:
            to_switch.write({'list_price_type': 'by_margin'})
        products._kai_update_planned_prices_from_replenishment()
        return products


class KaiCategoryMarginImport(models.TransientModel):
    _name = 'kai.category.margin.import'
    _description = 'Importar márgenes por categoría'

    data = fields.Text(
        string='Datos',
        required=True,
        help=(
            'Una categoría por línea, separada por punto y coma: '
            'nombre completo;margen %;recargo. El recargo es opcional. '
            'El nombre completo es el de la categoría con sus padres, '
            'por ejemplo «Bebidas / Gaseosas;40;5». También acepta el id. '
            'Las líneas vacías y las que empiezan con # se ignoran.'
        ),
    )
    apply_to_products = fields.Boolean(
        string='Aplicar a los productos sin margen propio',
        default=True,
        help=(
            'Pasa a «Por margen» los productos de esas categorías y de sus '
            'hijas que no tienen margen propio, y recalcula el precio de venta.'
        ),
    )

    def action_import(self):
        rows = self._kai_parse_rows()
        Category = self.env['product.category']
        missing = []
        found = Category.browse()
        for name, margin, surcharge in rows:
            category = self._kai_find_category(name)
            if not category:
                missing.append(name)
                continue
            category.write({
                'kai_margin_defined': True,
                'kai_margin_percent': margin,
                'kai_surcharge': surcharge,
            })
            found |= category
        if missing:
            raise UserError(_(
                'No se encontró una sola categoría para: %s',
                ', '.join(missing),
            ))
        if self.apply_to_products and found:
            found._kai_apply_margin_to_products()
        return {'type': 'ir.actions.act_window_close'}

    def _kai_parse_rows(self):
        self.ensure_one()
        rows = []
        for number, raw in enumerate((self.data or '').splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            separator = ';' if ';' in line else '\t'
            parts = [part.strip() for part in line.split(separator)]
            if len(parts) < 2 or not parts[0]:
                raise UserError(_(
                    'Línea %s: use «categoría;margen;recargo».',
                    number,
                ))
            try:
                margin = float(parts[1].replace(',', '.'))
                surcharge = float(parts[2].replace(',', '.')) if len(parts) > 2 and parts[2] else 0.0
            except ValueError as error:
                raise UserError(_(
                    'Línea %s: el margen y el recargo tienen que ser números.',
                    number,
                )) from error
            rows.append((parts[0], margin, surcharge))
        if not rows:
            raise UserError(_('No hay líneas para importar.'))
        return rows

    def _kai_find_category(self, name):
        Category = self.env['product.category']
        by_complete = Category.search([('complete_name', '=', name)])
        if len(by_complete) == 1:
            return by_complete
        if name.isdigit():
            by_id = Category.browse(int(name)).exists()
            if by_id:
                return by_id
        by_name = Category.search([('name', '=', name)])
        if len(by_name) == 1:
            return by_name
        return Category.browse()
