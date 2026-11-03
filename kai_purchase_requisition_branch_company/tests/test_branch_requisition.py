from odoo import Command
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestBranchRequisition(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        country = cls.env.ref('base.ar')
        cls.parent = cls.env['res.company'].create({
            'name': 'KAI Parent Co',
            'country_id': country.id,
        })
        cls.branch = cls.env['res.company'].create({
            'name': 'KAI Branch Co',
            'parent_id': cls.parent.id,
        })
        cls.user = cls.env['res.users'].create({
            'name': 'KAI Branch Buyer',
            'login': 'kai_branch_buyer',
            'company_id': cls.branch.id,
            'company_ids': [Command.set(cls.branch.ids)],
            'group_ids': [Command.set([
                cls.env.ref('base.group_user').id,
                cls.env.ref('purchase.group_purchase_user').id,
            ])],
        })
        cls.vendor = cls.env['res.partner'].create({'name': 'KAI Vendor'})
        cls.tax_group = cls.env['account.tax.group'].create({
            'name': 'KAI tax group',
            'company_id': cls.parent.id,
            'country_id': country.id,
        })
        cls.tax = cls.env['account.tax'].create({
            'name': 'KAI parent purchase tax',
            'tax_group_id': cls.tax_group.id,
            'country_id': country.id,
            'amount': 21,
            'type_tax_use': 'purchase',
            'company_id': cls.parent.id,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'KAI product',
            'type': 'consu',
            'supplier_taxes_id': [Command.set(cls.tax.ids)],
        })
        cls.requisition = cls.env['purchase.requisition'].with_company(cls.branch).create({
            'vendor_id': cls.vendor.id,
            'company_id': cls.branch.id,
            'requisition_type': 'purchase_template',
            'line_ids': [Command.create({
                'product_id': cls.product.id,
                'product_qty': 3,
                'price_unit': 10,
            })],
        })
        cls.requisition.action_confirm()

    def test_branch_user_selects_requisition(self):
        PurchaseOrder = self.env['purchase.order'].with_user(self.user).with_company(self.branch)
        form = Form(PurchaseOrder)
        form.partner_id = self.vendor
        form.requisition_id = self.requisition.with_user(self.user)
        order = form.save()
        self.assertEqual(order.company_id, self.branch)
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.order_line.product_id, self.product)
        self.assertEqual(order.order_line.sudo().tax_ids, self.tax)
