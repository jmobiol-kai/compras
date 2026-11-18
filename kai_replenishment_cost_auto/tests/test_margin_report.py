from datetime import date, datetime

from odoo import Command
from odoo.tests import tagged

from .common import KaiReplenishmentCommon


@tagged('post_install', '-at_install')
class TestMarginReport(KaiReplenishmentCommon):

    def test_invoice_cogs_and_uninvoiced_pos_without_double_count(self):
        expense = self.company_data['default_account_expense']
        self.assertTrue(
            expense.account_type.startswith('expense'),
            'La cuenta de gasto de la compañía de prueba no es de tipo expense*.',
        )
        if 'anglo_saxon_accounting' in self.env.company._fields:
            self.env.company.anglo_saxon_accounting = True
        stock_account = self.env['account.account'].create({
            'name': 'Valuación Kai',
            'code': 'KAIVAL',
            'account_type': 'asset_current',
        })
        category = self.env['product.category'].create({
            'name': 'Kai real time',
            'property_valuation': 'real_time',
            'property_cost_method': 'standard',
            'property_stock_valuation_account_id': stock_account.id,
            'property_account_income_categ_id': self.company_data['default_account_revenue'].id,
            'property_account_expense_categ_id': expense.id,
        })
        revenue = self.company_data['default_account_revenue']
        self.assertTrue(revenue.account_type.startswith('income'))
        product = self._goods(
            'Medialuna',
            categ_id=category.id,
            is_storable=True,
            standard_price=40.0,
            list_price=100.0,
            taxes_id=[Command.clear()],
            property_account_income_id=revenue.id,
            property_account_expense_id=expense.id,
        )
        product.standard_price = 40.0
        product.invalidate_recordset()
        self.assertEqual(product.valuation, 'real_time')

        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': date(2026, 6, 15),
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'name': product.name,
                'quantity': 1.0,
                'price_unit': 100.0,
                'tax_ids': [Command.clear()],
            })],
        })
        invoice.invoice_line_ids.write({
            'price_unit': 100.0,
            'quantity': 1.0,
            'tax_ids': [Command.clear()],
        })
        invoice.action_post()
        cogs_lines = invoice.line_ids.filtered(
            lambda line: line.display_type == 'cogs'
            and line.account_id.account_type.startswith('expense')
        )
        self.assertTrue(cogs_lines, 'La factura no generó la línea de CMV.')
        self.assertAlmostEqual(sum(cogs_lines.mapped('balance')), 40.0, places=2)

        when = datetime(2026, 6, 15, 15, 0, 0)
        session = self._pos_session()
        self._pos_line(session, product, subtotal=50.0, cost=20.0, when=when)
        self._pos_line(session, product, subtotal=80.0, cost=30.0, when=when, invoice=invoice)
        self._pos_line(session, product, subtotal=10.0, cost=4.0, when=when, refund=True)

        report = self.env['kai.margin.contribution.report'].search([
            ('product_id', '=', product.id),
            ('company_id', '=', self.env.company.id),
            ('date', '=', date(2026, 6, 1)),
        ])
        self.assertEqual(len(report), 1)
        # Factura 100 - CMV 40, POS no facturado 50 / 20, reembolso POS -10 / -4.
        # El POS facturado (80 / 30) no se suma.
        self.assertAlmostEqual(report.sales_amount, 140.0, places=2)
        self.assertAlmostEqual(report.cogs_amount, 56.0, places=2)
        self.assertAlmostEqual(report.margin_amount, 84.0, places=2)
        self.assertAlmostEqual(report.margin_percent, 60.0, places=2)

    def _pos_session(self):
        config = self.env['pos.config'].create({
            'name': 'Kai POS margin',
            'journal_id': self.company_data['default_journal_sale'].id,
            'invoice_journal_id': self.company_data['default_journal_sale'].id,
        })
        return self.env['pos.session'].create({'config_id': config.id})

    def _pos_line(self, session, product, subtotal, cost, when, invoice=None, refund=False):
        return self.env['pos.order'].create({
            'company_id': self.env.company.id,
            'session_id': session.id,
            'config_id': session.config_id.id,
            'state': 'paid',
            'is_refund': refund,
            'amount_tax': 0.0,
            'amount_total': subtotal,
            'amount_paid': subtotal,
            'amount_return': 0.0,
            'date_order': when,
            'account_move': invoice.id if invoice else False,
            'lines': [Command.create({
                'name': product.display_name,
                'product_id': product.id,
                'qty': -1.0 if refund else 1.0,
                'price_unit': subtotal,
                'price_subtotal': subtotal,
                'price_subtotal_incl': subtotal,
                'total_cost': cost,
                'is_total_cost_computed': True,
            })],
        })
