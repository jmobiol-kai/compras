from odoo import api, models

from .kai_no_create import extend_commercial_view_cache_key, guard_commercial_arch

# View hooks stay on each ``_inherit`` class. A plain mixin as a second base
# makes Odoo 19 fail while assigning ``__bases__`` (object layout differs).


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return extend_commercial_view_cache_key(self, key)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return guard_commercial_arch(self, arch, view_type), view


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return extend_commercial_view_cache_key(self, key)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return guard_commercial_arch(self, arch, view_type), view


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return extend_commercial_view_cache_key(self, key)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return guard_commercial_arch(self, arch, view_type), view


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return extend_commercial_view_cache_key(self, key)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return guard_commercial_arch(self, arch, view_type), view


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return extend_commercial_view_cache_key(self, key)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return guard_commercial_arch(self, arch, view_type), view


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return extend_commercial_view_cache_key(self, key)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return guard_commercial_arch(self, arch, view_type), view


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return extend_commercial_view_cache_key(self, key)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return guard_commercial_arch(self, arch, view_type), view
