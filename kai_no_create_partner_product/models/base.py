from odoo import api, models

from .kai_no_create import extend_commercial_view_cache_key, guard_commercial_arch


class Base(models.AbstractModel):
    """Apply the partner/product guard to every form, list and kanban view.

    ``_inherit = 'base'`` is the Odoo mixin. A plain Python base class breaks
    model layout on Odoo 19 while assigning ``__bases__``.
    """

    _inherit = 'base'

    @api.model
    def _get_view_cache_key(self, view_id=None, view_type='form', **options):
        key = super()._get_view_cache_key(view_id, view_type, **options)
        return extend_commercial_view_cache_key(self, key)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        return guard_commercial_arch(self, arch, view_type), view
