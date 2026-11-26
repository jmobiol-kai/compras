# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import _, fields, models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _create_diff_account_move_for_split_payment_method(self, payment_method, diff_amount):
        """Register a bank counting difference as a posted account.payment.

        Standard Odoo 19 creates a miscellaneous account.move on the bank
        journal. The accounting dashboard treats those lines (no payment_id,
        no statement_line_id) as "Operaciones misceláneas". For bank payment
        methods we create a payment instead, with the bank as outstanding
        account and the journal profit/loss account as destination. Cash
        keeps the standard behavior.
        """
        self.ensure_one()
        journal = payment_method.journal_id
        if not journal or journal.type != "bank":
            return super()._create_diff_account_move_for_split_payment_method(
                payment_method, diff_amount
            )

        bank_account = journal.default_account_id or payment_method.outstanding_account_id
        if not self._get_diff_vals(payment_method.id, diff_amount, outstanding_account=bank_account):
            return

        if self.currency_id.compare_amounts(diff_amount, 0) > 0:
            destination_account = journal.profit_account_id
            payment_type = "inbound"
            partner_type = "customer"
        else:
            destination_account = journal.loss_account_id
            payment_type = "outbound"
            partner_type = "supplier"

        if not destination_account or not bank_account:
            return

        payment_method_line = self._kai_manual_payment_method_line(journal, payment_type)
        vals = {
            "amount": abs(diff_amount),
            "date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "force_outstanding_account_id": bank_account.id,
            "destination_account_id": destination_account.id,
            "memo": _("Diferencia de cierre %s", self.name),
            "pos_payment_method_id": payment_method.id,
            "pos_session_id": self.id,
            "company_id": self.company_id.id,
            "payment_type": payment_type,
            "partner_type": partner_type,
        }
        if payment_method_line:
            vals["payment_method_line_id"] = payment_method_line.id

        payment = self.env["account.payment"].with_context(pos_payment=True).create(vals)
        self._ensure_payment_outstanding_account(payment, diff_amount)
        payment.action_post()
        if payment.move_id and payment.move_id.state == "draft":
            payment.move_id.action_post()

    def _kai_manual_payment_method_line(self, journal, payment_type):
        """Prefer the journal's Transferencia/Manual line for the payment type."""
        lines = (
            journal.inbound_payment_method_line_ids
            if payment_type == "inbound"
            else journal.outbound_payment_method_line_ids
        )
        return lines.filtered(lambda line: line.payment_method_id.code == "manual")[:1]
