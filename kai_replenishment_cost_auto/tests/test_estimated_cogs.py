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

    def test_price_refund_does_not_subtract_estimated_cogs(self):
        product = self._storable('Reembolso de precio')
        self._history(product, date(2026, 5, 1), 15.0)
        self._customer_invoice(product, date(2026, 6, 15), quantity=1.0, price=50.0, refund=True)
        report = self._report(product, date(2026, 6, 1))
        self.assertAlmostEqual(report.cogs_estimated, 0.0, places=2)
        self.assertAlmostEqual(report.cogs_amount, 0.0, places=2)
        self.assertAlmostEqual(report.sales_amount, -50.0, places=2)
        self.assertFalse(report.cost_origin)

    def test_credit_note_with_stock_return_subtracts_estimated_cogs(self):
        if 'sale.order' not in self.env or 'sale_line_id' not in self.env['stock.move']._fields:
            self.skipTest('sale_stock no está instalado')
        product = self._storable('Devolución con nota')
        self._history(product, date(2026, 5, 1), 15.0)
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'order_line': [Command.create({
                'product_id': product.id,
                'product_uom_qty': 1.0,
                'price_unit': 50.0,
                'tax_ids': [Command.clear()],
            })],
        })
        order.action_confirm()
        sale_line = order.order_line[:1]
        customers = self.env.ref('stock.stock_location_customers')
        warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        stock = warehouse.lot_stock_id
        Move = self.env['stock.move'].sudo()
        uom_field = 'product_uom_id' if 'product_uom_id' in Move._fields else 'product_uom'
        outgoing = Move.create({
            'name': product.name,
            'product_id': product.id,
            uom_field: product.uom_id.id,
            'product_uom_qty': 1.0,
            'location_id': stock.id,
            'location_dest_id': customers.id,
            'sale_line_id': sale_line.id,
            'company_id': self.env.company.id,
        })
        returned = Move.create({
            'name': 'Devolución',
            'product_id': product.id,
            uom_field: product.uom_id.id,
            'product_uom_qty': 1.0,
            'location_id': customers.id,
            'location_dest_id': stock.id,
            'sale_line_id': sale_line.id,
            'origin_returned_move_id': outgoing.id,
            'company_id': self.env.company.id,
        })
        self.env.cr.execute(
            "UPDATE stock_move SET state = 'done' WHERE id = %s",
            (returned.id,),
        )
        invoice = self._customer_invoice(
            product, date(2026, 6, 15), quantity=1.0, price=50.0, refund=True,
        )
        self.env.cr.execute(
            """
            INSERT INTO sale_order_line_invoice_rel (invoice_line_id, order_line_id)
            VALUES (%s, %s)
            """,
            (invoice.invoice_line_ids[:1].id, sale_line.id),
        )
        report = self._report(product, date(2026, 6, 1))
        self.assertEqual(report.cost_origin, 'history_before')
        self.assertAlmostEqual(report.cogs_estimated, -15.0, places=2)
        self.assertAlmostEqual(report.sales_amount, -50.0, places=2)

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
        self._history(finished, date(2026, 8, 1), 921.25)
        self._customer_invoice(finished, date(2026, 6, 15), quantity=1.0, price=40.0)
        report = self._report(finished, date(2026, 6, 1))
        self.assertEqual(report.cost_origin, 'bom')
        self.assertAlmostEqual(report.cogs_estimated, 10.0, places=2)

    def test_manufactured_prior_history_wins_over_bom(self):
        component = self._storable(
            'Masa con historial',
            replenishment_cost_type='last_supplier_price',
        )
        finished = self._storable(
            'Empanada con historial',
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
        self._history(finished, date(2026, 5, 10), 80.0)
        self._customer_invoice(finished, date(2026, 6, 15), quantity=1.0, price=40.0)
        report = self._report(finished, date(2026, 6, 1))
        self.assertEqual(report.cost_origin, 'history_before')
        self.assertAlmostEqual(report.cogs_estimated, 80.0, places=2)
