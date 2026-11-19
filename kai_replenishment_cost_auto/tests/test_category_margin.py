from odoo import Command
from odoo.tests import tagged

from .common import KaiReplenishmentCommon


@tagged('post_install', '-at_install')
class TestCategoryMargin(KaiReplenishmentCommon):

    def test_child_category_inherits_parent_margin(self):
        parent = self.env['product.category'].create({
            'name': 'Bebidas',
            'kai_margin_defined': True,
            'kai_margin_percent': 30.0,
            'kai_surcharge': 5.0,
        })
        child = self.env['product.category'].create({
            'name': 'Gaseosas',
            'parent_id': parent.id,
        })
        grandchild = self.env['product.category'].create({
            'name': 'Cola',
            'parent_id': child.id,
        })
        self.assertFalse(child.kai_margin_defined)
        self.assertAlmostEqual(child.kai_effective_margin_percent, 30.0)
        self.assertAlmostEqual(child.kai_effective_surcharge, 5.0)
        self.assertAlmostEqual(grandchild.kai_effective_margin_percent, 30.0)

        child.write({
            'kai_margin_defined': True,
            'kai_margin_percent': 40.0,
            'kai_surcharge': 1.0,
        })
        self.assertAlmostEqual(child.kai_effective_margin_percent, 40.0)
        self.assertAlmostEqual(grandchild.kai_effective_margin_percent, 40.0)
        self.assertAlmostEqual(parent.kai_effective_margin_percent, 30.0)

    def test_suggested_price_uses_category_or_product_margin(self):
        category = self.env['product.category'].create({
            'name': 'Panadería',
            'kai_margin_defined': True,
            'kai_margin_percent': 40.0,
            'kai_surcharge': 1.0,
        })
        child = self.env['product.category'].create({
            'name': 'Facturas',
            'parent_id': category.id,
        })
        product = self._goods(
            'Factura',
            categ_id=child.id,
            list_price=100.0,
            replenishment_cost_type='manual',
            replenishment_base_cost=100.0,
        )
        product.invalidate_recordset()
        # 100 × 1,40 + 1. Hereda el margen del padre.
        self.assertAlmostEqual(product.kai_suggested_price, 141.0, places=2)
        self.assertAlmostEqual(product.kai_price_difference, 41.0, places=2)
        self.assertAlmostEqual(product.kai_price_difference_percent, 41.0, places=2)
        self.assertAlmostEqual(product.list_price, 100.0, places=2)

        product.write({
            'kai_own_margin': True,
            'kai_margin_percent': 10.0,
            'kai_surcharge': 0.0,
        })
        product.invalidate_recordset()
        self.assertAlmostEqual(product.kai_suggested_price, 110.0, places=2)
        self.assertAlmostEqual(product.list_price, 100.0, places=2)

    def test_vendor_bill_does_not_change_list_price(self):
        category = self.env['product.category'].create({
            'name': 'Masas',
            'kai_margin_defined': True,
            'kai_margin_percent': 25.0,
            'kai_surcharge': 0.0,
        })
        component = self._goods(
            'Harina',
            categ_id=category.id,
            list_price=40.0,
            replenishment_cost_type='last_supplier_price',
        )
        finished = self._goods(
            'Tarta',
            categ_id=category.id,
            list_price=9.0,
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
        bill = self._vendor_bill(self.partner_a, [{
            'product': component,
            'price_unit': 100.0,
        }])
        bill.action_post()
        component.invalidate_recordset()
        finished.invalidate_recordset()
        self.assertAlmostEqual(component.replenishment_cost, 100.0, places=2)
        self.assertAlmostEqual(finished.replenishment_cost, 200.0, places=2)
        self.assertAlmostEqual(component.kai_suggested_price, 125.0, places=2)
        self.assertAlmostEqual(finished.kai_suggested_price, 250.0, places=2)
        self.assertAlmostEqual(component.list_price, 40.0, places=2)
        self.assertAlmostEqual(finished.list_price, 9.0, places=2)
