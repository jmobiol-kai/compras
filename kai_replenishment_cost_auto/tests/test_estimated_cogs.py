from datetime import date

from odoo import Command
from odoo.tests import tagged

from .common import KaiReplenishmentCommon


@tagged('post_install', '-at_install')
class TestEstimatedCogs(KaiReplenishmentCommon):

    def _manual_category(self):
        field = self.env['product.category']._fields['property_valuation']
        choices = {key for key, _label in field._description_selection(self.env)}
        if 'manual_periodic' in choices:
            valuation = 'manual_periodic'
        elif 'periodic' in choices:
            valuation = 'periodic'
        else:
            valuation = 'manual_periodic'
        return self.env['product.category'].create({
            'name': 'Kai sin CMV contable',
            'property_valuation': valuation,
            'property_cost_method': 'standard',
        })

    def _storable(self, name, **extra):
        vals = {
            'categ_id': self._manual_category().id,
            'is_storable': True,
            'sale_ok': True,
        }
        vals.update(extra)
        return self._goods(name, **vals)

    def _history(self, product, when, cost, state='posted'):
        return self.env['kai.replenishment.cost.history'].create({
            'date': when,
            'product_id': product.id,
            'product_tmpl_id': product.product_tmpl_id.id,
            'company_id': self.env.company.id,
            'currency_id': self.env.company.currency_id.id,
            'quantity': 1.0,
            'product_uom_id': product.uom_id.id,
            'price_unit': cost,
            'cost_previous': 0.0,
            'cost_new': cost,
            'variation_amount': cost,
            'variation_percent': 100.0,
            'origin': 'bill',
            'state': state,
        })

    def _customer_invoice(self, product, when, quantity=1.0, price=100.0, refund=False):
        revenue = self.company_data['default_account_revenue']
        invoice = self.env['account.move'].create({
            'move_type': 'out_refund' if refund else 'out_invoice',
            'partner_id': self.partner_a.id,
            'invoice_date': when,
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'name': product.name,
                'quantity': quantity,
                'price_unit': price,
                'account_id': revenue.id,
                'tax_ids': [Command.clear()],
            })],
        })
        invoice.invoice_line_ids.write({
            'quantity': quantity,
            'price_unit': price,
            'account_id': revenue.id,
            'tax_ids': [Command.clear()],
        })
        invoice.action_post()
        return invoice

    def _report(self, product, month):
        return self.env['kai.margin.contribution.report'].sudo().search([
            ('product_id', '=', product.id),
            ('company_id', '=', self.env.company.id),
            ('date', '=', month),
        ])

    def test_history_before_sale_estimates_cogs_without_a_journal_entry(self):
        product = self._storable('Factura sin FIFO')
        self._history(product, date(2026, 5, 1), 10.0, state='cancel')
        self._history(product, date(2026, 5, 2), 10.0)
        self._history(product, date(2026, 7, 1), 99.0)
        invoice = self._customer_invoice(product, date(2026, 6, 15), quantity=2.0, price=80.0)
        self.assertFalse(invoice.line_ids.filtered(lambda line: line.display_type == 'cogs'))

        report = self._report(product, date(2026, 6, 1))
        self.assertEqual(len(report), 1)
        self.assertEqual(report.cost_origin, 'history_before')
        self.assertTrue(report.has_estimated_cogs)
        self.assertAlmostEqual(report.sales_amount, 160.0, places=2)
        self.assertAlmostEqual(report.cogs_amount, 0.0, places=2)
        self.assertAlmostEqual(report.cogs_estimated, 20.0, places=2)
        self.assertAlmostEqual(report.cogs_total, 20.0, places=2)
        self.assertAlmostEqual(report.margin_amount, 140.0, places=2)

    def test_only_later_history_is_used_when_nothing_is_earlier(self):
        product = self._storable('Historial posterior')
        self._history(product, date(2026, 8, 1), 8.0)
        self._customer_invoice(product, date(2026, 6, 15), quantity=1.0, price=40.0)
        report = self._report(product, date(2026, 6, 1))
        self.assertEqual(report.cost_origin, 'history_after')
        self.assertAlmostEqual(report.cogs_estimated, 8.0, places=2)
        self.assertAlmostEqual(report.cogs_amount, 0.0, places=2)

    def test_without_history_uses_supplier_then_standard_price(self):
        supplied = self._storable('Sin historial con tarifa', standard_price=3.0)
        self._shared_seller(supplied, self.partner_a, 12.0)
        self._customer_invoice(supplied, date(2026, 6, 15), quantity=1.0, price=30.0)
        supplied_row = self._report(supplied, date(2026, 6, 1))
        self.assertEqual(supplied_row.cost_origin, 'replenishment')
        self.assertAlmostEqual(supplied_row.cogs_estimated, 12.0, places=2)

        standard = self._storable('Sin historial ni tarifa', standard_price=7.0)
        self._customer_invoice(standard, date(2026, 6, 15), quantity=1.0, price=30.0)
        standard_row = self._report(standard, date(2026, 6, 1))
        self.assertEqual(standard_row.cost_origin, 'standard')
        self.assertAlmostEqual(standard_row.cogs_estimated, 7.0, places=2)
        self.assertAlmostEqual(standard_row.cogs_total, 7.0, places=2)

    def test_accounting_cogs_is_not_duplicated_with_an_estimate(self):
        expense = self.company_data['default_account_expense']
        revenue = self.company_data['default_account_revenue']
        if 'anglo_saxon_accounting' in self.env.company._fields:
            self.env.company.anglo_saxon_accounting = True
        stock_account = self.env['account.account'].create({
            'name': 'Valuación estimada Kai',
            'code': 'KAIVALEST',
            'account_type': 'asset_current',
        })
        category = self.env['product.category'].create({
            'name': 'Kai real time estimado',
            'property_valuation': 'real_time',
            'property_cost_method': 'standard',
            'property_stock_valuation_account_id': stock_account.id,
            'property_account_income_categ_id': revenue.id,
            'property_account_expense_categ_id': expense.id,
        })
        product = self._goods(
            'Con CMV contable',
            categ_id=category.id,
            is_storable=True,
            standard_price=40.0,
            list_price=100.0,
            taxes_id=[Command.clear()],
            property_account_income_id=revenue.id,
            property_account_expense_id=expense.id,
        )
        product.standard_price = 40.0
        self._history(product, date(2026, 5, 1), 999.0)
        invoice = self._customer_invoice(product, date(2026, 6, 15), quantity=1.0, price=100.0)
        cogs = invoice.line_ids.filtered(
            lambda line: line.display_type == 'cogs'
            and line.account_id.account_type.startswith('expense')
        )
        self.assertTrue(cogs)
        report = self._report(product, date(2026, 6, 1))
        self.assertAlmostEqual(report.cogs_amount, 40.0, places=2)
        self.assertAlmostEqual(report.cogs_estimated, 0.0, places=2)
        self.assertAlmostEqual(report.cogs_total, 40.0, places=2)
        self.assertFalse(report.cost_origin)

    def test_credit_note_subtracts_estimated_cogs(self):
        product = self._storable('Nota de crédito')
        self._history(product, date(2026, 5, 1), 15.0)
        self._customer_invoice(product, date(2026, 6, 15), quantity=1.0, price=50.0, refund=True)
        report = self._report(product, date(2026, 6, 1))
        self.assertAlmostEqual(report.cogs_estimated, -15.0, places=2)
        self.assertAlmostEqual(report.cogs_amount, 0.0, places=2)
        self.assertAlmostEqual(report.sales_amount, -50.0, places=2)
        self.assertEqual(report.cost_origin, 'history_before')

    def test_manufactured_without_history_uses_component_history(self):
        component = self._storable(
            'Masa estimada',
            replenishment_cost_type='last_supplier_price',
        )
        finished = self._storable(
            'Empanada estimada',
            replenishment_cost_type='bom',
        )
        self.env['mrp.bom'].create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'product_uom_id': self.uom_unit.id,
            'type': 'normal',
            'company_id': False,
            'bom_line_ids': [Command.create({
                'product_id': component.id,
                'product_qty': 2.0,
                'product_uom_id': self.uom_unit.id,
            })],
        })
        self._history(component, date(2026, 5, 1), 5.0)
        self._customer_invoice(finished, date(2026, 6, 15), quantity=1.0, price=40.0)
        report = self._report(finished, date(2026, 6, 1))
        self.assertEqual(report.cost_origin, 'bom')
        self.assertAlmostEqual(report.cogs_estimated, 10.0, places=2)
