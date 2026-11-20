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

    def action_import(self):
        rows = self._kai_parse_rows()
        missing = []
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
        if missing:
            raise UserError(_(
                'No se encontró una sola categoría para: %s',
                ', '.join(missing),
            ))
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
