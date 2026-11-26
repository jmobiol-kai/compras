"""New purchase lines take the company cost, not the vendor price.

Run by Odoo, from a database where this module is installed:

    odoo-bin -d <db> -u kai_sale_category_delivery_report --test-enable --stop-after-init
"""
from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools.float_utils import float_compare


@tagged('post_install', '-at_install')
class TestPurchaseLineCost(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vendor = cls.env['res.partner'].create({
            'name': 'KAI Cost Vendor',
            'supplier_rank': 1,
        })
        cls.customer = cls.env['res.partner'].create({'name': 'KAI Cost Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'KAI Cost Product',
            'purchase_ok': True,
            'sale_ok': True,
            'list_price': 80.0,
            'standard_price': 10.0,
        })
        cls.env.user.tz = 'UTC'

    def _wizard(self):
        return self.env['kai.sale.category.delivery.wizard'].new({
            'partner_id': self.vendor.id,
            'delivery_date': fields.Date.today(),
            'categ_ids': [Command.set(self.product.categ_id.ids)],
        })

    def _purchase_line(self, product, qty=1.0, uom=None, currency=None, fiscal_position=None):
        vals = {
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
        }
        if currency:
            vals['currency_id'] = currency.id
        if fiscal_position:
            vals['fiscal_position_id'] = fiscal_position.id
        order = self.env['purchase.order'].create(vals)
        line_vals = {
            'order_id': order.id,
            'product_id': product.id,
            'product_qty': qty,
            'price_unit': 1.0,
        }
        if uom:
            line_vals['product_uom_id'] = uom.id
        line = self.env['purchase.order.line'].create(line_vals)
        return line

    def _price(self, line):
        return self._wizard()._line_cost_price_unit(line)

    def test_positive_cost_ignores_vendor_and_sale_price(self):
        self.product.standard_price = 12.5
        self.env['product.supplierinfo'].create({
            'partner_id': self.vendor.id,
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'price': 99.0,
        })
        line = self._purchase_line(self.product)
        price = self._price(line)
        self.assertEqual(price, 12.5)
        self.assertNotEqual(price, 99.0)
        self.assertNotEqual(price, 80.0)
        self.assertEqual(self.product.standard_price, 12.5)

    def test_zero_cost_stays_zero_even_with_vendor_price(self):
        self.product.standard_price = 0.0
        self.env['product.supplierinfo'].create({
            'partner_id': self.vendor.id,
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'price': 40.0,
        })
        line = self._purchase_line(self.product)
        self.assertEqual(self._price(line), 0.0)
        self.assertEqual(self.product.standard_price, 0.0)

    def test_cost_is_the_purchase_company_cost(self):
        other = self.env['res.company'].create({'name': 'KAI Cost Other'})
        self.product.with_company(self.company).standard_price = 5.0
        self.product.with_company(other).standard_price = 9.0
        line = self._purchase_line(self.product)
        self.assertEqual(line.order_id.company_id, self.company)
        self.assertEqual(self._price(line), 5.0)
        other_order = self.env['purchase.order'].with_company(other).create({
            'partner_id': self.vendor.id,
            'company_id': other.id,
        })
        other_line = self.env['purchase.order.line'].with_company(other).create({
            'order_id': other_order.id,
            'product_id': self.product.id,
            'product_qty': 1.0,
            'price_unit': 1.0,
        })
        self.assertEqual(
            self._wizard().with_company(other)._line_cost_price_unit(other_line),
            9.0,
        )
        self.assertEqual(self.product.with_company(self.company).standard_price, 5.0)
        self.assertEqual(self.product.with_company(other).standard_price, 9.0)

    def test_cost_converts_from_product_uom_to_line_uom(self):
        self.product.standard_price = 10.0
        dozen = self.env.ref('uom.product_uom_dozen')
        line = self._purchase_line(self.product, qty=1.0, uom=dozen)
        self.assertEqual(line.product_uom_id, dozen)
        self.assertEqual(self._price(line), 120.0)

    def test_cost_converts_company_currency_and_rounds(self):
        self.product.standard_price = 10.0
        foreign = self.env['res.currency'].create({
            'name': 'KCX',
            'symbol': 'K',
            'rounding': 0.01,
        })
        self.env['res.currency.rate'].create({
            'currency_id': foreign.id,
            'rate': 1.23456,
            'name': fields.Date.today(),
            'company_id': self.company.id,
        })
        self.vendor.property_purchase_currency_id = foreign
        line = self._purchase_line(self.product, currency=foreign)
        self.assertEqual(line.order_id.currency_id, foreign)
        expected = foreign.round(10.0 * 1.23456)
        self.assertEqual(expected, 12.35)
        self.assertEqual(self._price(line), expected)

    def test_included_tax_removed_by_fiscal_position_is_not_charged_again(self):
        tax_group = self.env['account.tax.group'].search([
            ('company_id', '=', self.company.id),
        ], limit=1)
        included = self.env['account.tax'].create({
            'name': 'KAI 21 incl',
            'amount': 21.0,
            'type_tax_use': 'purchase',
            'price_include_override': 'tax_included',
            'company_id': self.company.id,
            'tax_group_id': tax_group.id,
        })
        excluded = self.env['account.tax'].create({
            'name': 'KAI 21 excl',
            'amount': 21.0,
            'type_tax_use': 'purchase',
            'price_include_override': 'tax_excluded',
            'company_id': self.company.id,
            'tax_group_id': tax_group.id,
            'original_tax_ids': [Command.set(included.ids)],
        })
        position = self.env['account.fiscal.position'].create({
            'name': 'KAI strip included',
            'company_id': self.company.id,
            'tax_ids': [Command.set(excluded.ids)],
        })
        self.product.standard_price = 121.0
        self.product.supplier_taxes_id = included
        line = self._purchase_line(self.product, fiscal_position=position)
        self.assertIn(excluded, line.tax_ids)
        self.assertNotIn(included, line.tax_ids)
        price = self._price(line)
        stripped = included.compute_all(121.0, currency=self.company.currency_id)['total_excluded']
        self.assertEqual(
            float_compare(price, stripped, precision_rounding=self.company.currency_id.rounding),
            0,
        )
        self.assertLess(price, 121.0)
        self.assertEqual(self.product.standard_price, 121.0)

    def test_generated_purchase_line_uses_cost_and_leaves_product_cost(self):
        self.product.standard_price = 4.5
        self.env['product.supplierinfo'].create({
            'partner_id': self.vendor.id,
            'product_tmpl_id': self.product.product_tmpl_id.id,
            'price': 30.0,
        })
        categ = self.env['product.category'].create({'name': 'KAI Cost Category'})
        self.product.categ_id = categ
        day = fields.Date.today()
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'commitment_date': fields.Datetime.to_datetime(day).replace(hour=12),
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': 12.0,
            })],
        })
        sale.action_confirm()
        wizard = self.env['kai.sale.category.delivery.wizard'].create({
            'categ_ids': [Command.set(categ.ids)],
            'delivery_date': day,
            'partner_id': self.vendor.id,
        })
        wizard.action_show()
        action = wizard.action_create_purchase_order()
        order = self.env['purchase.order'].browse(action['res_id'])
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.price_unit, 4.5)
        self.assertEqual(order.order_line.product_qty, 12.0)
        self.assertTrue(order.order_line.kai_allocation_ids)
        self.assertEqual(self.product.standard_price, 4.5)
        # A second generation finds the draft coverage and buys nothing.
        with self.assertRaises(UserError):
            wizard.action_create_purchase_order()
