# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

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
        self.assertFalse(self.pos_session.kai_search_cash_move_partners('P'))
        journals = self.pos_session.kai_list_cash_move_dest_journals()
        journal_ids = [row['id'] for row in journals]
        self.assertNotIn(self.pos_session.cash_journal_id.id, journal_ids)
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
