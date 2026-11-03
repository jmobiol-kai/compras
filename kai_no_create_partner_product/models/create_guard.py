from odoo import _, api, models
from odoo.exceptions import UserError

from .kai_no_create import commercial_create_is_blocked


class CommercialCreateGuard:
    """Reject partner and product creates that come from a guarded document.

    Quick create calls ``name_create``, which calls ``create``. The form dialog
    calls ``web_save``, which also calls ``create``. Blocking ``create`` covers
    both. The many2one context is the only signal that distinguishes this from
    a create done in Contactos or Productos.
    """

    @api.model_create_multi
    def create(self, vals_list):
        if vals_list and commercial_create_is_blocked(self.env):
            raise UserError(self._kai_commercial_create_message())
        return super().create(vals_list)

    def _kai_commercial_create_message(self):
        if self._name == 'res.partner':
            return _(
                'No tiene permitido crear contactos desde cotizaciones, facturas o recibos. '
                'Elija un contacto existente o pida a un administrador que active '
                '«Permitir creación de productos y contactos desde las cotizaciones» en su usuario.'
            )
        return _(
            'No tiene permitido crear productos desde cotizaciones, facturas o recibos. '
            'Elija un producto existente o pida a un administrador que active '
            '«Permitir creación de productos y contactos desde las cotizaciones» en su usuario.'
        )


class ResPartner(CommercialCreateGuard, models.Model):
    _inherit = 'res.partner'


class ProductProduct(CommercialCreateGuard, models.Model):
    _inherit = 'product.product'


class ProductTemplate(CommercialCreateGuard, models.Model):
    _inherit = 'product.template'
