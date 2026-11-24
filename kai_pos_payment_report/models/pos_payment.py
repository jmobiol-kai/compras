# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class PosPayment(models.Model):
    _inherit = "pos.payment"

    config_id = fields.Many2one(
        "pos.config",
        string="Point of Sale",
        related="pos_order_id.config_id",
        store=True,
        index=True,
    )
    sales_journal_id = fields.Many2one(
        "account.journal",
        string="Invoicing Journal",
        compute="_compute_sales_journal_id",
        store=True,
        index=True,
        help="Journal of the POS order invoice (Ventas FE or Ventas X). "
             "If the order is not invoiced yet, the configured invoice or "
             "batch (X) journal of the point of sale is used.",
    )
    payment_date_date = fields.Date(
        string="Payment Day",
        compute="_compute_payment_date_date",
        store=True,
        index=True,
        help="Payment date in the company timezone, for day filters and grouping.",
    )
    payment_medium_type = fields.Selection(
        selection=[
            ("efectivo", "Cash"),
            ("electronico", "Electronic"),
        ],
        string="Payment Medium Type",
        compute="_compute_payment_medium_type",
        store=True,
        index=True,
        help="Cash if the method is marked for cash count or uses a cash "
             "journal; otherwise electronic. Used to group the report and "
             "the Excel export.",
    )

    @api.depends(
        "pos_order_id",
        "pos_order_id.account_move",
        "pos_order_id.account_move.journal_id",
        "pos_order_id.config_id",
        "pos_order_id.config_id.invoice_journal_id",
    )
    def _compute_sales_journal_id(self):
        for payment in self:
            payment.sales_journal_id = payment._kai_sales_journal_for_order(
                payment.pos_order_id
            )

    def _kai_sales_journal_for_order(self, order):
        """Resolve the sales journal without requiring msb_pos_facturacion_lotes.

        Priority: invoice journal if the order is invoiced; else the explicit
        batch journal on the order; else config.default_journalx when the
        order is flagged use_batch_journal; else the POS invoice journal.
        """
        if not order:
            return self.env["account.journal"]
        if order.account_move:
            return order.account_move.journal_id
        batch_journal = getattr(order, "batch_invoice_journal_id", False)
        if batch_journal:
            return batch_journal
        use_batch = getattr(order, "use_batch_journal", False)
        if use_batch:
            journalx = getattr(order.config_id, "default_journalx", False)
            if journalx:
                return journalx
        return order.config_id.invoice_journal_id if order.config_id else self.env["account.journal"]

    @api.depends("payment_date", "company_id")
    def _compute_payment_date_date(self):
        for payment in self:
            if not payment.payment_date:
                payment.payment_date_date = False
                continue
            tz = (
                payment.company_id.partner_id.tz
                or payment.env.user.tz
                or "America/Argentina/Buenos_Aires"
            )
            payment.payment_date_date = fields.Datetime.context_timestamp(
                payment.with_context(tz=tz),
                payment.payment_date,
            ).date()

    @api.model
    def _kai_is_cash_method(self, method):
        """Same cash rule used by the Excel export and Tipo de medio."""
        if not method:
            return False
        if method.is_cash_count:
            return True
        journal = method.journal_id
        return bool(journal) and journal.type == "cash"

    @api.depends(
        "payment_method_id",
        "payment_method_id.is_cash_count",
        "payment_method_id.journal_id",
        "payment_method_id.journal_id.type",
    )
    def _compute_payment_medium_type(self):
        for payment in self:
            if payment._kai_is_cash_method(payment.payment_method_id):
                payment.payment_medium_type = "efectivo"
            else:
                payment.payment_medium_type = "electronico"

