# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import shutil
import subprocess
from pathlib import Path

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestKaiPosCashMovePartner(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.vendor = cls.env['res.partner'].create({'name': 'Proveedor POS Kai'})
        cls.customer = cls.env['res.partner'].create({'name': 'Cliente POS Kai'})
        cls.cashier = cls.env['res.partner'].create({'name': 'Cajero POS Kai'})

    def setUp(self):
        super().setUp()
        self.open_new_session()

    def _cash(self, kind, amount, reason, partner_id=False, extras=None):
        payload = {'translatedType': kind}
        if extras:
            payload.update(extras)
        before = self.pos_session.statement_line_ids
        self.pos_session.try_cash_in_out(kind, amount, reason, partner_id, payload)
        return (self.pos_session.statement_line_ids - before)[:1]

    def _bill(self, amount, invoice_date=None, partner=None):
        return self.init_invoice(
            'in_invoice',
            partner=partner or self.vendor,
            invoice_date=invoice_date,
            amounts=[amount],
            taxes=[],
            post=True,
        )

    def _invoice(self, amount, invoice_date=None):
        return self.init_invoice(
            'out_invoice',
            partner=self.customer,
            invoice_date=invoice_date,
            amounts=[amount],
            taxes=[],
            post=True,
        )

    def _payable_line(self, st_line, partner):
        account = partner.with_company(st_line.company_id).property_account_payable_id
        return st_line.move_id.line_ids.filtered(lambda line: line.account_id == account)

    def _receivable_line(self, st_line, partner):
        account = partner.with_company(st_line.company_id).property_account_receivable_id
        return st_line.move_id.line_ids.filtered(lambda line: line.account_id == account)

    def test_plain_cash_out_stays_unassigned(self):
        line = self._cash('out', 25.0, 'Cambio')
        self.assertFalse(line.cash_move_assigned)
        self.assertTrue(line.cash_move_partner_pending)
        self.assertFalse(line.partner_id)
        self.assertFalse(line.cash_move_contact_id)

    def test_supplier_surplus_stays_on_account_and_cashier_stays(self):
        bill = self._bill(40.0)
        line = self._cash('out', 100.0, 'Pago de más', self.cashier.id, {
            'cash_partner_id': self.vendor.id,
            'move_ids': bill.ids,
        })
        self.assertTrue(line.cash_move_assigned)
        self.assertEqual(line.partner_id, self.cashier)
        self.assertEqual(line.move_id.partner_id, self.vendor)
        self.assertEqual(line.cash_move_contact_id, self.vendor)
        self.assertEqual(line.vendor_bill_id, bill)
        self.assertEqual(line.vendor_bill_ids, bill)
        self.assertIn(bill.payment_state, ('paid', 'in_payment'))
        payable = self._payable_line(line, self.vendor)
        self.assertEqual(payable.partner_id, self.vendor)
        self.assertFalse(payable.reconciled)
        self.assertAlmostEqual(abs(payable.amount_residual), 60.0)

    def test_supplier_several_bills_oldest_first(self):
        older = self._bill(40.0, '2019-01-01')
        newer = self._bill(40.0, '2019-06-01')
        line = self._cash('out', 100.0, 'Pago varias', self.cashier.id, {
            'cash_partner_id': self.vendor.id,
            'move_ids': (older | newer).ids,
        })
        self.assertIn(older.payment_state, ('paid', 'in_payment'))
        self.assertIn(newer.payment_state, ('paid', 'in_payment'))
        self.assertEqual(line.vendor_bill_id, older)
        self.assertEqual(line.vendor_bill_ids, older | newer)
        self.assertEqual(line.partner_id, self.cashier)
        payable = self._payable_line(line, self.vendor)
        self.assertAlmostEqual(abs(payable.amount_residual), 20.0)
        line.action_unassign_cash_move_partner()
        self.assertFalse(line.vendor_bill_ids)
        self.assertFalse(line.cash_move_assigned)
        self.assertEqual(older.payment_state, 'not_paid')
        self.assertEqual(newer.payment_state, 'not_paid')

    def test_supplier_partial_when_cash_does_not_cover_the_bills(self):
        older = self._bill(40.0, '2019-01-01')
        newer = self._bill(40.0, '2019-06-01')
        self._cash('out', 30.0, 'Pago parcial', self.cashier.id, {
            'cash_partner_id': self.vendor.id,
            'move_ids': (older | newer).ids,
        })
        self.assertEqual(older.payment_state, 'partial')
        self.assertAlmostEqual(older.amount_residual, 10.0)
        self.assertEqual(newer.payment_state, 'not_paid')

    def test_wizard_still_rejects_supplier_surplus(self):
        line = self._cash('out', 100.0, 'Wizard estricto')
        bill = self._bill(40.0)
        with self.assertRaises(UserError) as error:
            line._assign_cash_move_to_partner(self.vendor, bill=bill)
        self.assertIn('más grande', str(error.exception))
        self.assertFalse(line.cash_move_assigned)

    def test_customer_invoices_and_on_account(self):
        invoice = self._invoice(40.0)
        line = self._cash('in', 100.0, 'Cobro', self.cashier.id, {
            'cash_partner_id': self.customer.id,
            'move_ids': invoice.ids,
        })
        self.assertEqual(line.partner_id, self.cashier)
        self.assertEqual(line.move_id.partner_id, self.customer)
        self.assertIn(invoice, line.customer_invoice_ids)
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))
        receivable = self._receivable_line(line, self.customer)
        self.assertEqual(receivable.partner_id, self.customer)
        self.assertAlmostEqual(abs(receivable.amount_residual), 60.0)

        on_account = self._cash('in', 15.0, 'Seña', self.cashier.id, {
            'cash_partner_id': self.customer.id,
        })
        self.assertTrue(on_account.cash_move_assigned)
        self.assertFalse(on_account.customer_invoice_ids)
        self.assertEqual(on_account.partner_id, self.cashier)
        self.assertEqual(on_account.cash_move_contact_id, self.customer)
        self.assertEqual(on_account.kai_on_account_payment_id.memo, 'Seña')
        self.assertEqual(on_account.kai_on_account_payment_id.partner_id, self.customer)

    def test_customer_invoices_do_not_create_a_receipt(self):
        invoice = self._invoice(40.0)
        before = self.env['account.payment'].search_count([])
        line = self._cash('in', 40.0, 'Cobro factura', self.cashier.id, {
            'cash_partner_id': self.customer.id,
            'move_ids': invoice.ids,
        })
        self.assertEqual(self.env['account.payment'].search_count([]), before)
        self.assertFalse(line.kai_on_account_payment_id)
        self.assertIn(invoice.payment_state, ('paid', 'in_payment'))

    def test_customer_on_account_receipt_keeps_reason_and_can_be_imputed(self):
        """Entrada with a contact and no invoice is a customer receipt.

        The cash debit stays on the POS statement line only. The receipt memo
        is the cashier's note, the open receivable is not applied to invoices
        that already existed, and a later invoice can take that credit.
        """
        already_open = self._invoice(40.0)
        before = self.env['account.payment'].search_count([])
        line = self._cash('in', 15.0, '  Seña cumpleaños  ', self.cashier.id, {
            'cash_partner_id': self.customer.id,
        })
        payment = line.kai_on_account_payment_id
        self.assertTrue(payment)
        self.assertEqual(self.env['account.payment'].search_count([]), before + 1)
        self.assertEqual(payment.memo, 'Seña cumpleaños')
        self.assertEqual(payment.move_id.ref, 'Seña cumpleaños')
        self.assertEqual(payment.payment_type, 'inbound')
        self.assertEqual(payment.partner_type, 'customer')
        self.assertEqual(payment.partner_id, self.customer)
        self.assertAlmostEqual(payment.amount, 15.0)
        self.assertIn(payment.state, ('in_process', 'paid'))
        self.assertEqual(payment.pos_session_id, self.pos_session)
        self.assertTrue(line.cash_move_assigned)
        self.assertFalse(line.cash_move_partner_pending)
        self.assertFalse(line.customer_invoice_ids)
        self.assertEqual(line.partner_id, self.cashier)
        self.assertEqual(line.move_id.partner_id, self.customer)
        self.assertEqual(already_open.payment_state, 'not_paid')
        self.assertAlmostEqual(already_open.amount_residual, 40.0)

        cash_account = line.journal_id.default_account_id
        cash_lines = (line.move_id.line_ids | payment.move_id.line_ids).filtered(
            lambda move_line: move_line.account_id == cash_account
        )
        self.assertEqual(len(cash_lines), 1)
        self.assertAlmostEqual(cash_lines.balance, 15.0)
        bridge_lines = (line.move_id.line_ids | payment.move_id.line_ids).filtered(
            lambda move_line: move_line.account_id == payment.outstanding_account_id
        )
        self.assertEqual(len(bridge_lines), 2)
        self.assertTrue(all(bridge_lines.mapped('reconciled')))

        receivable = self.customer.with_company(line.company_id).property_account_receivable_id
        credit = payment.move_id.line_ids.filtered(
            lambda move_line: move_line.account_id == receivable
        )
        self.assertEqual(len(credit), 1)
        self.assertFalse(credit.reconciled)
        self.assertAlmostEqual(abs(credit.amount_residual), 15.0)

        later = self._invoice(10.0)
        debit = later.line_ids.filtered(
            lambda move_line: move_line.account_id == receivable and not move_line.reconciled
        )
        (credit | debit).reconcile()
        self.assertIn(later.payment_state, ('paid', 'in_payment'))
        self.assertAlmostEqual(later.amount_residual, 0.0)
        self.assertAlmostEqual(abs(credit.amount_residual), 5.0)
        self.assertEqual(already_open.payment_state, 'not_paid')

        with self.assertRaises(UserError) as error:
            line.action_unassign_cash_move_partner()
        self.assertIn('imputó', str(error.exception))
        self.assertEqual(line.kai_on_account_payment_id, payment)
        self.assertNotEqual(payment.state, 'canceled')
        self.assertIn(later.payment_state, ('paid', 'in_payment'))

    def test_customer_on_account_undo_cancels_the_receipt(self):
        line = self._cash('in', 15.0, 'Seña sin imputar', self.cashier.id, {
            'cash_partner_id': self.customer.id,
        })
        payment = line.kai_on_account_payment_id
        line.action_unassign_cash_move_partner()
        self.assertFalse(line.kai_on_account_payment_id)
        self.assertFalse(line.cash_move_assigned)
        self.assertTrue(line.cash_move_partner_pending)
        self.assertFalse(line.partner_id)
        self.assertFalse(line.cash_move_contact_id)
        self.assertEqual(payment.state, 'canceled')
        self.assertFalse(payment.move_id.line_ids.filtered(
            lambda move_line: move_line.account_id.account_type == 'asset_receivable'
            and move_line.parent_state == 'posted'
            and not move_line.reconciled
        ))

    def test_child_contact_receipt_uses_the_commercial_partner(self):
        child = self.env['res.partner'].create({
            'name': 'Hijo POS Kai',
            'parent_id': self.customer.id,
        })
        line = self._cash('in', 8.0, 'Seña hijo', self.cashier.id, {
            'cash_partner_id': child.id,
        })
        self.assertEqual(line.kai_on_account_payment_id.partner_id, self.customer)
        self.assertEqual(line.kai_on_account_payment_id.memo, 'Seña hijo')
        self.assertEqual(line.cash_move_contact_id, self.customer)

    def test_dest_journal_uses_onlyone_transfer(self):
        journal = self.company_data['default_journal_bank']
        self.env['pos.cash.move.type'].create({
            'name': 'Pasar a otra caja Kai',
            'direction': 'both',
            'counterpart_mode': 'journal',
            'partner_policy': 'forbidden',
        })
        line = self._cash('out', 80.0, 'A la caja fuerte', self.cashier.id, {
            'dest_journal_id': journal.id,
            'cash_partner_id': self.vendor.id,
            'move_ids': [],
        })
        self.assertEqual(line.cash_move_journal_id, journal)
        self.assertTrue(line.cash_move_mirror_line_id)
        self.assertEqual(line.cash_move_mirror_line_id.journal_id, journal)
        self.assertFalse(line.cash_move_mirror_line_id.pos_session_id)
        self.assertAlmostEqual(line.cash_move_mirror_line_id.amount, 80.0)
        self.assertEqual(line.partner_id, self.cashier)
        self.assertFalse(line.move_id.partner_id)
        self.assertFalse(line.vendor_bill_id)

    def test_dest_journal_without_partner(self):
        """Salida with a destination journal and no contact still transfers.

        The cashier can move the drawer to another cash or bank journal,
        such as Efectivo Tesoro, without choosing a partner.
        """
        journal = self.company_data['default_journal_bank']
        self.env['pos.cash.move.type'].create({
            'name': 'Pasar a tesoro Kai',
            'direction': 'both',
            'counterpart_mode': 'journal',
            'partner_policy': 'optional',
        })
        line = self._cash('out', 80.0, 'A Efectivo Tesoro', self.cashier.id, {
            'dest_journal_id': journal.id,
        })
        self.assertEqual(line.cash_move_journal_id, journal)
        self.assertTrue(line.cash_move_mirror_line_id)
        self.assertEqual(line.cash_move_mirror_line_id.journal_id, journal)
        self.assertFalse(line.cash_move_mirror_line_id.pos_session_id)
        self.assertAlmostEqual(line.cash_move_mirror_line_id.amount, 80.0)
        self.assertEqual(line.partner_id, self.cashier)
        self.assertFalse(line.move_id.partner_id)
        self.assertFalse(line.cash_move_contact_id)
        self.assertFalse(line.vendor_bill_id)
        self.assertFalse(line.customer_invoice_ids)
        self.assertFalse(line.kai_on_account_payment_id)

    def test_dest_journal_requires_a_configured_type(self):
        journal = self.company_data['default_journal_bank']
        with self.assertRaises(UserError) as error:
            self._cash('out', 10.0, 'Sin tipo', self.cashier.id, {
                'dest_journal_id': journal.id,
            })
        self.assertIn('Tipos de caja', str(error.exception))

    def test_session_journal_is_rejected(self):
        self.env['pos.cash.move.type'].create({
            'name': 'Destino de esta sesión',
            'direction': 'both',
            'counterpart_mode': 'journal',
            'partner_policy': 'forbidden',
        })
        with self.assertRaises(UserError):
            self._cash('out', 10.0, 'Misma caja', self.cashier.id, {
                'dest_journal_id': self.pos_session.cash_journal_id.id,
            })

    def test_lists_open_documents_and_other_journals(self):
        bill = self._bill(50.0)
        invoice = self._invoice(70.0)
        bills = self.pos_session.kai_list_cash_move_open_documents(self.vendor.id, 'out')
        invoices = self.pos_session.kai_list_cash_move_open_documents(self.customer.id, 'in')
        self.assertIn(bill.id, [row['id'] for row in bills])
        self.assertNotIn(invoice.id, [row['id'] for row in bills])
        self.assertIn(invoice.id, [row['id'] for row in invoices])
        self.assertNotIn(bill.id, [row['id'] for row in invoices])
        partners = self.pos_session.kai_search_cash_move_partners('Proveedor POS')
        self.assertIn(self.vendor.id, [row['id'] for row in partners])
        # One letter is a valid query (no minimum length). The RPC still
        # returns at most 20 rows, so a common letter must not be expected
        # to include a specific partner.
        one_letter = self.pos_session.kai_search_cash_move_partners('P')
        self.assertTrue(one_letter)
        self.assertLessEqual(len(one_letter), 20)
        needle = self.env['res.partner'].create({'name': 'Zz9KaiCashMove'})
        found = self.pos_session.kai_search_cash_move_partners('Zz9')
        self.assertIn(needle.id, [row['id'] for row in found])
        opened = self.pos_session.kai_search_cash_move_partners('')
        self.assertTrue(opened)
        self.assertLessEqual(len(opened), 20)
        payload = self.pos_session.kai_list_cash_move_dest_journals()
        journals = payload['journals']
        journal_ids = [row['id'] for row in journals]
        cash_journal = self.pos_session.cash_journal_id
        self.assertEqual(payload['session_cash_journal_id'], cash_journal.id)
        self.assertEqual(
            payload['session_cash_journal_name'], cash_journal.sudo().display_name,
        )
        self.assertNotIn(cash_journal.id, journal_ids)
        self.assertIn(self.company_data['default_journal_bank'].id, journal_ids)
        self.assertTrue(all(row['type'] in ('bank', 'cash') for row in journals))

    def test_pos_manager_can_record_on_account(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Admin POS kai',
            'login': 'pos_admin_kai_cash_move',
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('point_of_sale.group_pos_manager').id,
            ])],
        })
        before = self.pos_session.statement_line_ids
        self.pos_session.with_user(user).try_cash_in_out(
            'out', 20.0, 'Anticipo', user.partner_id.id,
            {'translatedType': 'out', 'cash_partner_id': self.vendor.id},
        )
        line = (self.pos_session.statement_line_ids - before)[:1]
        self.assertTrue(line.cash_move_assigned)
        self.assertEqual(line.partner_id, user.partner_id)
        self.assertEqual(line.cash_move_contact_id, self.vendor)
        self.assertFalse(line.vendor_bill_id)

    def test_popup_direction_switch_clears_partner_documents_and_journal(self):
        """Entrada and salida must not keep the other's contact, bills or journal.

        The popup state lives in the POS client. The check runs the same
        module source the cashier loads. Salida without a contact can still
        choose a destination journal.
        """
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed')
        script = Path(__file__).resolve().parent / 'js' / 'cash_move_popup_direction.test.mjs'
        result = subprocess.run(
            [node, str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, (result.stdout or '') + (result.stderr or ''))
