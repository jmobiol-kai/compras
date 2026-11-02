from odoo import api, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.onchange('journal_id')
    def _onchange_journal_id_company_id(self):
        """Same company selection as core, without reading the parent company.

        ``account_payment_pro`` (workaround for odoo/odoo#212762) drops the
        compute dependency of ``company_id`` and calls ``_compute_company_id``
        from this onchange. Core then evaluates::

            journal.company_id not in payment.company_id.parent_ids

        ``res.company.parent_ids`` is filled with ``compute_sudo`` from
        ``parent_path``, but the value is still returned in the caller's
        environment. The recordset includes every ancestor. Odoo 19 filters
        ``active`` when converting an x2many, and that fetch applies the
        multi-company rule. A user allowed only on a branch (Happ under
        Blinis SA) gets AccessError on Empresas (res.company) as soon as
        the payment journal changes.

        ``company.sudo().parent_ids`` is used only for the id membership
        test. ``company_id`` is still assigned from ``_accessible_branches()``
        on the non-sudo company, so this onchange does not write an elevated
        record onto the NewId payment. ``super()`` is not called: the parent
        method is the ``_compute_company_id()`` call that raises.
        """
        for payment in self:
            if payment.journal_id.company_id not in payment.company_id.sudo().parent_ids:
                payment.company_id = (
                    payment.journal_id.company_id or self.env.company
                )._accessible_branches()[:1]
