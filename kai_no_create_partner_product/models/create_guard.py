from odoo import api, models

from .kai_no_create import check_commercial_create

# ``create`` stays on the ``_inherit`` class. A plain mixin as a second base
# makes Odoo 19 fail while assigning ``__bases__`` (object layout differs).


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        check_commercial_create(self, vals_list)
        return super().create(vals_list)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model_create_multi
    def create(self, vals_list):
        check_commercial_create(self, vals_list)
        return super().create(vals_list)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        check_commercial_create(self, vals_list)
        return super().create(vals_list)
