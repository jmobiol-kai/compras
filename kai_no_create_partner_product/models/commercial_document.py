from lxml import etree

from odoo import api, models

from .kai_no_create import COMMERCIAL_VIEW_TYPES, restrict_partner_product_m2o


class CommercialViewGuard:
    """Apply ``no_create`` on partner and product many2ones of one document model.

    ``get_view`` caches the arch without the user id (see ``_get_view_cache_key``
    on the base model). The flag is part of the key, so two users with different
    values do not share an arch, and toggling the checkbox changes the key on
    the next load.
    """

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        return super()._get_view_cache_key(view_id, view_type, **options) + (
            bool(self.env.user.kai_allow_create_partner_product),
        )

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        if (
            view_type in COMMERCIAL_VIEW_TYPES
            and not self.env.user.kai_allow_create_partner_product
        ):
            # Copy before editing. The combined arch must stay intact for users
            # who are still allowed to create.
            arch = etree.fromstring(etree.tostring(arch))
            restrict_partner_product_m2o(arch, self)
        return arch, view


class SaleOrder(CommercialViewGuard, models.Model):
    _inherit = 'sale.order'


class SaleOrderLine(CommercialViewGuard, models.Model):
    _inherit = 'sale.order.line'


class PurchaseOrder(CommercialViewGuard, models.Model):
    _inherit = 'purchase.order'


class PurchaseOrderLine(CommercialViewGuard, models.Model):
    _inherit = 'purchase.order.line'


class AccountMove(CommercialViewGuard, models.Model):
    _inherit = 'account.move'


class AccountMoveLine(CommercialViewGuard, models.Model):
    _inherit = 'account.move.line'


class AccountPayment(CommercialViewGuard, models.Model):
    _inherit = 'account.payment'
