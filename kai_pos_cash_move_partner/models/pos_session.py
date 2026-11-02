# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import _, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import formatLang, format_date

_PAYMENT_LABEL = {
    'not_paid': 'Sin pagar',
    'partial': 'Parcial',
    'in_payment': 'En pago',
    'paid': 'Pagada',
}


class PosSession(models.Model):
    _inherit = 'pos.session'

    def try_cash_in_out(self, _type, amount, reason, partner_id, extras):
        """Create the cash move, then assign the contact from ``extras``.

        ``partner_id`` stays the cashier (the POS user partner, or the
        employee work contact when pos_hr is installed). The commercial
        contact travels in ``extras`` and is passed to
        ``_assign_cash_move_to_partner``. Keys:

        * ``cash_partner_id``: ``res.partner`` id.
        * ``move_ids``: open ``out_invoice`` ids on a cash in, or
          ``in_invoice`` / ``in_receipt`` ids on a cash out.
        * ``dest_journal_id``: other cash or bank journal. When it is set,
          invoices are not applied. The transfer uses a journal-mode
          ``pos.cash.move.type`` of the session company.
        """
        extras = extras or {}
        before_ids = set(self.sudo().statement_line_ids.ids)
        result = super().try_cash_in_out(_type, amount, reason, partner_id, extras)
        if not self._kai_cash_move_extras_requested(extras):
            return result
        new_lines = self.env['account.bank.statement.line'].sudo().search([
            ('pos_session_id', 'in', self.ids),
            ('id', 'not in', list(before_ids)),
        ])
        # Checks run as the cashier. OnlyOne sudos the statement-line write.
        new_lines.sudo(False)._kai_assign_pos_cash_move(extras)
        new_lines.sudo(False)._kai_restore_cashier_partner(partner_id)
        return result

    def _kai_cash_move_extras_requested(self, extras):
        if not isinstance(extras, dict):
            return False
        return bool(
            extras.get('cash_partner_id')
            or extras.get('dest_journal_id')
            or extras.get('move_ids')
        )

    def _kai_check_cash_move_access(self):
        self.ensure_one()
        if not self.env.user._has_cash_move_permission():
            raise AccessError(_('No podés registrar una entrada o salida de efectivo.'))
        if not self.cash_journal_id:
            raise UserError(_('Esta sesión no tiene diario de caja.'))

    def kai_search_cash_move_partners(self, query):
        """Partners the cashier can attach to this session's cash move."""
        self.ensure_one()
        self._kai_check_cash_move_access()
        query = (query or '').strip()[:80]
        if len(query) < 2:
            return []
        domain = [
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id),
            '|', '|', '|',
            ('name', 'ilike', query),
            ('vat', 'ilike', query),
            ('ref', 'ilike', query),
            ('email', 'ilike', query),
        ]
        partners = self.env['res.partner'].search(domain, limit=20, order='name, id')
        return [{
            'id': partner.id,
            'name': partner.display_name,
            'vat': partner.vat or '',
        } for partner in partners]

    def kai_list_cash_move_open_documents(self, partner_id, cash_type):
        """Open customer invoices or vendor bills for this session company."""
        self.ensure_one()
        self._kai_check_cash_move_access()
        try:
            partner_id = int(partner_id)
        except (TypeError, ValueError):
            return []
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            return []
        commercial = partner.commercial_partner_id
        company = self.company_id
        if cash_type == 'out':
            domain = [
                ('move_type', 'in', ('in_invoice', 'in_receipt')),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('amount_residual', '>', 0),
                ('company_id', '=', company.id),
                ('commercial_partner_id', '=', commercial.id),
            ]
        elif cash_type == 'in':
            currency = self.cash_journal_id.currency_id or company.currency_id
            domain = [
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('amount_residual', '>', 0),
                ('company_id', '=', company.id),
                ('currency_id', '=', currency.id),
                ('commercial_partner_id', '=', commercial.id),
            ]
        else:
            raise UserError(_('El sentido del movimiento no es válido.'))
        moves = self.env['account.move'].search(
            domain, order='invoice_date asc, id asc', limit=80,
        )
        return [self._kai_cash_move_document_payload(move) for move in moves]

    def kai_list_cash_move_dest_journals(self):
        """Other cash and bank journals of the session company.

        The session cash journal is excluded. A POS manager has no read
        access on ``account.journal``, so the search is sudo and the domain
        stays on this company, these types and the session currency.
        """
        self.ensure_one()
        self._kai_check_cash_move_access()
        cash_journal = self.cash_journal_id
        cash_currency = cash_journal.currency_id or self.company_id.currency_id
        journals = self.env['account.journal'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('type', 'in', ('bank', 'cash')),
            ('id', '!=', cash_journal.id),
            ('active', '=', True),
        ], order='type, name, id')
        result = []
        for journal in journals:
            currency = journal.currency_id or journal.company_id.currency_id
            if currency != cash_currency:
                continue
            result.append({
                'id': journal.id,
                'name': journal.display_name,
                'type': journal.type,
            })
        return result

    def _kai_cash_move_document_payload(self, move):
        self.ensure_one()
        return {
            'id': move.id,
            'name': move.name or '',
            'ref': move.ref or '',
            'invoice_date': format_date(self.env, move.invoice_date) if move.invoice_date else '',
            'payment_state': move.payment_state,
            'payment_label': _PAYMENT_LABEL.get(move.payment_state, ''),
            'amount_residual': move.amount_residual,
            'amount_total': move.amount_total,
            'currency': move.currency_id.name or '',
            'amount_residual_display': formatLang(
                self.env, move.amount_residual, currency_obj=move.currency_id,
            ),
        }
