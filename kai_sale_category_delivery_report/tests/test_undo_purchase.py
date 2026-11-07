"""Undo returns the generated RFQ to an empty draft with the same number."""
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestUndoPurchaseTrace(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.tz = 'UTC'
        cls.vendor = cls.env['res.partner'].create({
            'name': 'KAI Undo Vendor',
            'supplier_rank': 1,
        })
        cls.customer = cls.env['res.partner'].create({'name': 'KAI Undo Customer'})
        cls.categ = cls.env['product.category'].create({'name': 'KAI Undo Category'})
        cls.product = cls.env['product.product'].create({
            'name': 'KAI Undo Product',
            'purchase_ok': True,
            'sale_ok': True,
            'categ_id': cls.categ.id,
            'list_price': 50.0,
            'standard_price': 6.0,
        })
        cls.other_product = cls.env['product.product'].create({
            'name': 'KAI Undo Other',
            'purchase_ok': True,
            'sale_ok': True,
            'categ_id': cls.categ.id,
            'standard_price': 3.0,
        })
        cls.consumidor = cls.env['res.partner'].create({
            'name': 'Consumidor Final Anónimo',
        })

    def _generate(self, product=None, qty=12.0):
        product = product or self.product
        day = fields.Date.today()
        sale = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'commitment_date': fields.Datetime.to_datetime(day).replace(hour=15),
            'order_line': [Command.create({
                'product_id': product.id,
                'product_uom_qty': qty,
            })],
        })
        sale.action_confirm()
        wizard = self.env['kai.sale.category.delivery.wizard'].create({
            'categ_ids': [Command.set(self.categ.ids)],
            'delivery_date': day,
            'partner_id': self.vendor.id,
        })
        wizard.action_show()
        action = wizard.action_create_purchase_order()
        purchase = self.env['purchase.order'].browse(action['res_id'])
        return sale, purchase

    def test_undo_reuses_the_same_draft_without_old_links(self):
        sale, purchase = self._generate()
        purchase.partner_ref = 'FAC-PROVEEDOR'
        origin = purchase.origin
        self.assertTrue(self.env['purchase.order']._kai_origin_is_report_label(origin))
        name = purchase.name
        purchase_id = purchase.id
        sale_line = sale.order_line

        purchase.action_kai_undo_sale_trace()

        self.assertEqual(purchase.id, purchase_id)
        self.assertEqual(purchase.name, name)
        self.assertEqual(purchase.state, 'draft')
        self.assertFalse(purchase.order_line)
        self.assertFalse(purchase.kai_allocation_ids)
        self.assertEqual(purchase.kai_sale_order_count, 0)
        self.assertEqual(purchase.partner_id, self.consumidor)
        self.assertEqual(purchase.partner_ref, 'FAC-PROVEEDOR')
        expected_position = self.env['account.fiscal.position'].with_company(
            purchase.company_id
        )._get_fiscal_position(self.consumidor)
        self.assertEqual(purchase.fiscal_position_id, expected_position)
        self.assertFalse(purchase.origin)
        self.assertTrue(sale_line.exists())
        self.assertEqual(sale.state, 'sale')
        self.assertEqual(self.product.standard_price, 6.0)

        purchase.write({
            'order_line': [Command.create({
                'product_id': self.other_product.id,
                'product_qty': 1.0,
                'price_unit': 3.0,
            })],
        })
        purchase.button_confirm()
        self.assertEqual(purchase.state, 'purchase')
        self.assertFalse(purchase.kai_allocation_ids)
        self.assertEqual(purchase.id, purchase_id)
        self.assertEqual(purchase.name, name)

        wizard = self.env['kai.sale.category.delivery.wizard'].create({
            'categ_ids': [Command.set(self.categ.ids)],
            'delivery_date': fields.Date.today(),
            'partner_id': self.vendor.id,
        })
        wizard.action_show()
        purchase_b = self.env['purchase.order'].browse(
            wizard.action_create_purchase_order()['res_id']
        )
        self.assertNotEqual(purchase_b.id, purchase.id)
        self.assertEqual(purchase_b.order_line.product_id, self.product)
        self.assertEqual(purchase_b.order_line.product_qty, 12.0)
        self.assertEqual(purchase_b.order_line.price_unit, 6.0)
        self.assertEqual(purchase_b.kai_allocation_ids.sale_line_id, sale.order_line)
        self.assertFalse(purchase.kai_allocation_ids)
        self.assertEqual(sale.state, 'sale')

    def test_cancel_then_undo_returns_to_empty_draft(self):
        sale, purchase = self._generate()
        purchase.button_cancel()
        self.assertEqual(purchase.state, 'cancel')
        self.assertTrue(purchase.order_line)
        self.assertTrue(purchase.kai_allocation_ids)
        purchase.action_kai_undo_sale_trace()
        self.assertEqual(purchase.state, 'draft')
        self.assertFalse(purchase.order_line)
        self.assertFalse(purchase.kai_allocation_ids)
        self.assertTrue(sale.order_line.exists())

    def test_confirmed_order_and_second_undo_are_refused(self):
        sale, purchase = self._generate()
        purchase.button_confirm()
        self.assertEqual(purchase.state, 'purchase')
        with self.assertRaises(UserError):
            purchase.action_kai_undo_sale_trace()
        self.assertEqual(purchase.state, 'purchase')
        self.assertTrue(purchase.order_line)
        self.assertTrue(purchase.kai_allocation_ids)
        self.assertTrue(sale.order_line.exists())

        draft_sale, draft_purchase = self._generate(product=self.other_product, qty=2.0)
        draft_purchase.action_kai_undo_sale_trace()
        with self.assertRaises(UserError):
            draft_purchase.action_kai_undo_sale_trace()
        self.assertEqual(draft_purchase.state, 'draft')
        self.assertTrue(draft_sale.order_line.exists())

    def test_vendor_bill_blocks_undo(self):
        _sale, purchase = self._generate()
        line = purchase.order_line
        self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.vendor.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product.id,
                'quantity': 1.0,
                'price_unit': 6.0,
                'purchase_line_id': line.id,
            })],
        })
        with self.assertRaises(UserError):
            purchase.action_kai_undo_sale_trace()
        self.assertTrue(purchase.order_line)
        self.assertTrue(purchase.kai_allocation_ids)

    def test_other_purchase_allocation_survives(self):
        _sale_a, purchase_a = self._generate()
        product_b = self.other_product
        sale_b = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({
                'product_id': product_b.id,
                'product_uom_qty': 2.0,
            })],
        })
        sale_b.action_confirm()
        purchase_b = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
        })
        line_b = self.env['purchase.order.line'].create({
            'order_id': purchase_b.id,
            'product_id': product_b.id,
            'product_qty': 2.0,
            'price_unit': 3.0,
        })
        allocation_b = self.env['kai.sale.po.allocation'].create({
            'company_id': self.env.company.id,
            'sale_line_id': sale_b.order_line.id,
            'purchase_line_id': line_b.id,
            'purchase_order_id': purchase_b.id,
            'product_id': product_b.id,
            'product_uom_id': product_b.uom_id.id,
            'quantity': 2.0,
        })
        purchase_a.action_kai_undo_sale_trace()
        self.assertTrue(allocation_b.exists())
        self.assertEqual(allocation_b.purchase_order_id, purchase_b)
        self.assertEqual(purchase_b.order_line, line_b)

    def test_sales_user_cannot_undo(self):
        _sale, purchase = self._generate()
        user = self.env['res.users'].create({
            'name': 'KAI Undo Sales',
            'login': 'kai_undo_sales_only',
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('sales_team.group_sale_salesman').id,
            ])],
        })
        refused = False
        try:
            purchase.with_user(user).action_kai_undo_sale_trace()
        except (AccessError, UserError):
            refused = True
        self.assertTrue(refused)
        self.assertTrue(purchase.order_line)
        self.assertTrue(purchase.kai_allocation_ids)

    def test_manual_origin_and_normal_cancel_are_kept(self):
        _sale, purchase = self._generate()
        purchase.origin = 'Pedido manual'
        purchase.button_cancel()
        self.assertEqual(purchase.state, 'cancel')
        self.assertTrue(purchase.order_line)
        self.assertTrue(purchase.kai_allocation_ids)
        self.assertEqual(purchase.origin, 'Pedido manual')
        purchase.action_kai_undo_sale_trace()
        self.assertEqual(purchase.origin, 'Pedido manual')
        self.assertEqual(purchase.state, 'draft')
        self.assertEqual(purchase.partner_id, self.consumidor)

    def test_missing_or_ambiguous_or_other_company_rolls_back(self):
        _sale, purchase = self._generate()
        self.consumidor.unlink()
        with self.assertRaises(UserError):
            purchase.action_kai_undo_sale_trace()
        self.assertEqual(purchase.state, 'draft')
        self.assertEqual(purchase.partner_id, self.vendor)
        self.assertTrue(purchase.order_line)
        self.assertTrue(purchase.kai_allocation_ids)

        first = self.env['res.partner'].create({'name': 'Consumidor Final Anónimo'})
        second = self.env['res.partner'].create({'name': 'Consumidor Final Anónimo'})
        with self.assertRaises(UserError):
            purchase.action_kai_undo_sale_trace()
        self.assertEqual(purchase.partner_id, self.vendor)
        self.assertTrue(purchase.order_line)
        first.unlink()
        second.unlink()

        other = self.env['res.company'].create({'name': 'KAI Undo Other Company'})
        self.env['res.partner'].create({
            'name': 'Consumidor Final Anónimo',
            'company_id': other.id,
        })
        with self.assertRaises(UserError):
            purchase.action_kai_undo_sale_trace()
        self.assertEqual(purchase.partner_id, self.vendor)
        self.assertTrue(purchase.order_line)
        self.assertTrue(purchase.kai_allocation_ids)

    def test_official_xmlid_wins_over_another_same_name(self):
        _sale, purchase = self._generate()
        self.env['res.partner'].create({'name': 'Consumidor Final Anónimo'})
        self.env['ir.model.data'].create({
            'module': 'l10n_ar',
            'name': 'par_cfa',
            'model': 'res.partner',
            'res_id': self.consumidor.id,
            'noupdate': True,
        })
        purchase.partner_ref = 'REF-MANUAL'
        purchase.action_kai_undo_sale_trace()
        self.assertEqual(purchase.partner_id, self.consumidor)
        self.assertEqual(purchase.partner_ref, 'REF-MANUAL')
        self.assertEqual(purchase.state, 'draft')
        self.assertFalse(purchase.order_line)
