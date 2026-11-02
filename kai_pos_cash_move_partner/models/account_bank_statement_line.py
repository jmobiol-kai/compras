# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import Command, _, fields, models
from odoo.exceptions import UserError


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    vendor_bill_ids = fields.Many2many(
        comodel_name='account.move',
        relation='kai_pos_cash_move_vendor_bill_rel',
        column1='statement_line_id',
        column2='bill_id',
        string='Facturas de proveedor',
        readonly=True,
        copy=False,
        help='Facturas de proveedor aplicadas desde el punto de venta. '
             'La más vieja también queda en Factura de proveedor.',
    )
    cash_move_contact_id = fields.Many2one(
        comodel_name='res.partner',
        string='Contacto',
        related='move_id.partner_id',
        readonly=True,
        help='Contacto comercial del asiento. En la línea de caja, Quién '
             'sigue siendo el cajero cuando el movimiento se confirma en el POS.',
    )

    def _check_vendor_bill(self, partner, bill):
        """Allow a POS cash-out to leave the surplus on the payable account.

        OnlyOne rejects a withdrawal larger than the selected bill. From the
        POS the cashier can apply one or more bills and keep the remainder
        as pago a cuenta, the same way a customer collection leaves a surplus
        on the receivable. The backend wizard does not set this context, so
        it still rejects that surplus.
        """
        self.ensure_one()
        if not self.env.context.get('kai_allow_vendor_surplus'):
            return super()._check_vendor_bill(partner, bill)
        return self._kai_check_vendor_bill_identity(partner, bill)

    def _kai_check_vendor_bill_identity(self, partner, bill):
        """OnlyOne's supplier checks, without the surplus comparison."""
        self.ensure_one()
        if bill and bill.move_type in ('out_refund', 'in_refund'):
            raise UserError(_('Las notas de crédito no se marcan acá.'))
        if not bill:
            return
        if bill.move_type not in ('in_invoice', 'in_receipt') or bill.state != 'posted':
            raise UserError(_('Esa factura todavía no está confirmada.'))
        if bill.company_id != self.company_id:
            raise UserError(_('Esa factura es de otra empresa.'))
        if bill.commercial_partner_id != partner.commercial_partner_id:
            raise UserError(_('Esa factura es de otro proveedor.'))
        if bill.payment_state in ('paid', 'in_payment', 'reversed'):
            raise UserError(_('Esa factura ya está pagada.'))

    def _undo_cash_move_partner(self):
        super()._undo_cash_move_partner()
        if self.vendor_bill_ids:
            self.sudo().with_context(skip_account_move_synchronization=True).write({
                'vendor_bill_ids': [Command.clear()],
            })

    def _kai_assign_pos_cash_move(self, extras):
        for st_line in self:
            st_line._kai_assign_pos_cash_move_one(extras or {})

    def _kai_assign_pos_cash_move_one(self, extras):
        """Call OnlyOne's assignment with the contact chosen in the POS popup."""
        self.ensure_one()
        partner = self._kai_partner_from_extras(extras)
        dest_journal = self._kai_dest_journal_from_extras(extras)
        moves = self._kai_moves_from_extras(extras)
        if dest_journal:
            return self._kai_assign_dest_journal(partner, dest_journal)
        if moves and not partner:
            raise UserError(_('Elegí el contacto de esas facturas.'))
        if not partner:
            return False
        if self.cash_move_partner_direction == 'supplier':
            wrong = moves.filtered(
                lambda move: move.move_type not in ('in_invoice', 'in_receipt')
            )
            if wrong:
                raise UserError(_('Esas facturas no son de proveedor.'))
            return self._kai_assign_vendor_bills(partner, moves)
        if self.cash_move_partner_direction == 'customer':
            return self._kai_assign_customer_invoices(partner, moves)
        raise UserError(_('Este movimiento no se puede usar.'))

    def _kai_assign_customer_invoices(self, partner, invoices):
        self.ensure_one()
        invoices = invoices or self.env['account.move']
        if invoices.filtered(lambda move: move.move_type != 'out_invoice'):
            raise UserError(_('Esas facturas no son de cliente.'))
        return self._assign_cash_move_to_partner(partner, invoices=invoices)

    def _kai_assign_vendor_bills(self, partner, bills):
        """Pay the oldest bill through OnlyOne, then the remainder.

        ``_assign_cash_move_to_partner`` stores a single ``vendor_bill_id``
        and reconciles that bill. Further bills are applied oldest first.
        Money that is left stays open on the payable account.
        """
        self.ensure_one()
        bills = (bills or self.env['account.move']).exists()
        ctx_self = self.with_context(kai_allow_vendor_surplus=True)
        if not bills:
            return ctx_self._assign_cash_move_to_partner(partner)
        ordered = bills.sorted(key=lambda move: (move.invoice_date or move.date, move.id))
        for bill in ordered:
            ctx_self._check_vendor_bill(partner, bill)
        if len(ordered) == 1:
            result = ctx_self._assign_cash_move_to_partner(partner, bill=ordered)
            self._kai_store_vendor_bills(ordered)
            return result
        account = ctx_self._kai_check_vendor_bills_same_account(partner, ordered)
        result = ctx_self._assign_cash_move_to_partner(partner, bill=ordered[:1])
        self._kai_reconcile_extra_vendor_bills(ordered[1:], account)
        self._kai_store_vendor_bills(ordered)
        return result

    def _kai_check_vendor_bills_same_account(self, partner, bills):
        self.ensure_one()
        account = self._get_cash_move_partner_account(partner, bill=bills[:1])
        if not account:
            raise UserError(_('No se puede anotar este pago para ese proveedor.'))
        for bill in bills:
            payable = bill.line_ids.filtered(
                lambda line: line.account_id.account_type == 'liability_payable'
                and not line.reconciled
            )
            if not payable or payable.account_id != account:
                raise UserError(_('Esa factura no se puede pagar con la cuenta de ese proveedor.'))
        return account

    def _kai_reconcile_extra_vendor_bills(self, bills, account):
        """Same oldest-first remainder as OnlyOne's customer collections."""
        self.ensure_one()
        if not bills or not account:
            return
        ordered = bills.sorted(key=lambda move: (move.invoice_date or move.date, move.id))
        for bill in ordered:
            payment_lines = self.sudo().move_id.line_ids.filtered(
                lambda line: line.account_id == account and not line.reconciled
            )
            if not payment_lines:
                break
            currency = payment_lines[:1].currency_id
            residual = sum(payment_lines.mapped('amount_residual'))
            if currency.is_zero(residual):
                break
            bill_lines = bill.sudo().line_ids.filtered(
                lambda line: line.account_id == account and not line.reconciled
            )
            if bill_lines:
                (payment_lines | bill_lines).reconcile()

    def _kai_store_vendor_bills(self, bills):
        self.sudo().with_context(skip_account_move_synchronization=True).write({
            'vendor_bill_ids': [Command.set(bills.ids)],
        })

    def _kai_assign_dest_journal(self, partner, dest_journal):
        """Transfer through a journal-mode ``pos.cash.move.type``.

        OnlyOne creates the mirror line only when ``_assign_cash_move_to_partner``
        receives ``cash_move_type`` and ``dest_journal``. The POS popup asks for
        the journal; the type is the one configured in Tipos de caja.
        """
        self.ensure_one()
        move_type = self._kai_journal_move_type(dest_journal, partner)
        assign_partner = partner or None
        if move_type.partner_policy == 'forbidden':
            assign_partner = None
        return self._assign_cash_move_to_partner(
            partner=assign_partner,
            cash_move_type=move_type,
            dest_journal=dest_journal,
        )

    def _kai_journal_move_type(self, dest_journal, partner):
        self.ensure_one()
        types = self.env['pos.cash.move.type'].search([
            ('company_id', '=', self.company_id.id),
            ('counterpart_mode', '=', 'journal'),
            ('direction', 'in', (self._line_flow(), 'both')),
        ])
        if not types:
            raise UserError(_(
                'Para pasar la plata a otra caja o al banco, primero cargá un tipo '
                'en Punto de venta, Tipos de caja, con destino Otra caja o banco.'
            ))

        def score(move_type):
            points = 0
            if move_type.default_journal_id == dest_journal:
                points += 4
            elif not move_type.default_journal_id:
                points += 2
            if partner and move_type.partner_policy in ('optional', 'required'):
                points += 1
            if not partner and move_type.partner_policy in ('forbidden', 'optional'):
                points += 1
            return (points, -move_type.id)

        return max(types, key=score)

    def _kai_partner_from_extras(self, extras):
        partner_id = extras.get('cash_partner_id')
        if not partner_id:
            return self.env['res.partner']
        try:
            partner_id = int(partner_id)
        except (TypeError, ValueError):
            raise UserError(_('Ese contacto no es válido.')) from None
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            raise UserError(_('No se encontró ese contacto.'))
        return partner

    def _kai_moves_from_extras(self, extras):
        raw = extras.get('move_ids') or []
        if isinstance(raw, int):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            raise UserError(_('Las facturas no son válidas.'))
        ids = []
        for item in raw:
            try:
                ids.append(int(item))
            except (TypeError, ValueError):
                raise UserError(_('Las facturas no son válidas.')) from None
        if not ids:
            return self.env['account.move']
        moves = self.env['account.move'].browse(ids).exists()
        if len(moves) != len(set(ids)):
            raise UserError(_('No se encontró una de esas facturas.'))
        if any(move.company_id != self.company_id for move in moves):
            raise UserError(_('Esa factura es de otra empresa.'))
        return moves

    def _kai_dest_journal_from_extras(self, extras):
        journal_id = extras.get('dest_journal_id')
        if not journal_id:
            return self.env['account.journal']
        try:
            journal_id = int(journal_id)
        except (TypeError, ValueError):
            raise UserError(_('Ese diario no es válido.')) from None
        # A POS manager can confirm a cash move without read access on journals.
        journal = self.env['account.journal'].sudo().browse(journal_id).exists()
        if (
            not journal
            or journal.company_id != self.company_id
            or journal.type not in ('bank', 'cash')
            or journal == self.journal_id
        ):
            raise UserError(_('Elegí otra caja o el banco, no la de esta sesión.'))
        cash_currency = self.journal_id.currency_id or self.company_id.currency_id
        journal_currency = journal.currency_id or journal.company_id.currency_id
        if journal_currency != cash_currency:
            raise UserError(_('Ese diario está en otra moneda.'))
        return journal

    def _kai_restore_cashier_partner(self, cashier_partner_id):
        """Keep the statement-line partner as the cashier.

        ``account.bank.statement.line.partner_id`` is its own column.
        ``move_id.partner_id`` is the journal entry partner. OnlyOne writes
        the commercial contact on both. This puts the cashier back on the
        statement line only. ``skip_account_move_synchronization`` keeps the
        receivable or payable lines on the commercial contact.
        """
        cashier_id = False
        if cashier_partner_id:
            try:
                cashier_id = int(cashier_partner_id)
            except (TypeError, ValueError):
                cashier_id = False
            else:
                cashier = self.env['res.partner'].sudo().browse(cashier_id).exists()
                cashier_id = cashier.id or False
        self.sudo().with_context(skip_account_move_synchronization=True).write({
            'partner_id': cashier_id,
        })
