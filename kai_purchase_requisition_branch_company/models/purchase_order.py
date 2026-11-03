from odoo import api, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.onchange('requisition_id')
    def _onchange_requisition_id(self):
        """Let branch-only users pick a purchase agreement (Contrato).

        Core ``purchase_requisition`` builds the RFQ lines with::

            line.product_id.supplier_taxes_id.filtered(
                lambda tax: tax.company_id in requisition.company_id.parent_ids)

        ``res.company.parent_ids`` is computed with ``compute_sudo`` from
        ``parent_path``, so it contains every ancestor (Blinis SA for the
        Happ branch). Odoo 19 filters ``active`` when it converts an x2many
        value to records, and fetching ``active`` on the parent company
        applies the multi-company record rule
        (``[('id', 'in', company_ids)]``). A user allowed only on the branch
        gets AccessError on Empresas (res.company) as soon as the Contrato
        field is set.

        Only the ``active`` flag of the ancestor companies is loaded here,
        with sudo, into the transaction cache. Core then reads it from the
        cache and the rest of the onchange runs unchanged in the user's
        environment: no record is written with elevated rights and nothing
        else about the parent company is exposed.
        """
        companies = self.requisition_id.company_id
        if companies:
            companies.sudo().parent_ids.mapped('active')
        return super()._onchange_requisition_id()
