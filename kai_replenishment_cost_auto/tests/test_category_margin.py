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
        self.assertAlmostEqual(child.kai_effective_surcharge, 1.0)
        self.assertAlmostEqual(grandchild.kai_effective_margin_percent, 40.0)
        self.assertAlmostEqual(parent.kai_effective_margin_percent, 30.0)

    def test_product_override_beats_category_margin(self):
        category = self.env['product.category'].create({
            'name': 'Panadería',
            'kai_margin_defined': True,
            'kai_margin_percent': 40.0,
            'kai_surcharge': 1.0,
        })
        product = self._goods(
            'Factura',
            categ_id=category.id,
            list_price_type='by_margin',
            replenishment_cost_type='manual',
            replenishment_base_cost=100.0,
        )
        product.invalidate_recordset()
        self.assertFalse(product.kai_own_margin)
        self.assertAlmostEqual(product.computed_list_price, 141.0, places=2)

        product.write({
            'kai_own_margin': True,
            'sale_margin': 10.0,
            'sale_surcharge': 0.0,
        })
        product.invalidate_recordset()
        self.assertAlmostEqual(product.computed_list_price, 110.0, places=2)

    def test_vendor_bill_recomputes_sale_price_from_category_margin(self):
        category = self.env['product.category'].create({
            'name': 'Masas',
            'kai_margin_defined': True,
            'kai_margin_percent': 25.0,
            'kai_surcharge': 10.0,
        })
        component = self._goods(
            'Harina',
            categ_id=category.id,
            list_price_type='by_margin',
            replenishment_cost_type='last_supplier_price',
            sale_margin=0.0,
        )
        finished = self._goods(
            'Tarta',
            categ_id=category.id,
            list_price_type='by_margin',
            replenishment_cost_type='bom',
            sale_margin=99.0,
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
        # El 99 del producto no se usa: no tiene margen propio.
        self.assertAlmostEqual(component.list_price, 135.0, places=2)
        self.assertAlmostEqual(finished.replenishment_cost, 200.0, places=2)
        self.assertAlmostEqual(finished.list_price, 260.0, places=2)

    def test_apply_button_sets_by_margin_except_own_override(self):
        category = self.env['product.category'].create({
            'name': 'Fiambres',
            'kai_margin_defined': True,
            'kai_margin_percent': 20.0,
            'kai_surcharge': 0.0,
        })
        child = self.env['product.category'].create({
            'name': 'Cocidos',
            'parent_id': category.id,
        })
        inherited = self._goods(
            'Jamón',
            categ_id=child.id,
            list_price_type='manual',
            replenishment_cost_type='manual',
            replenishment_base_cost=50.0,
            list_price=1.0,
        )
        own = self._goods(
            'Salame',
            categ_id=child.id,
            list_price_type='manual',
            kai_own_margin=True,
            sale_margin=5.0,
            replenishment_cost_type='manual',
            replenishment_base_cost=50.0,
            list_price=7.0,
        )
        category.action_kai_apply_margin()
        inherited.invalidate_recordset()
        own.invalidate_recordset()
        self.assertEqual(inherited.list_price_type, 'by_margin')
        self.assertAlmostEqual(inherited.list_price, 60.0, places=2)
        self.assertEqual(own.list_price_type, 'manual')
        self.assertAlmostEqual(own.list_price, 7.0, places=2)

    def test_import_wizard_sets_category_margin(self):
        category = self.env['product.category'].create({'name': 'Lácteos'})
        wizard = self.env['kai.category.margin.import'].create({
            'data': 'Lácteos;15;2\n# comentario\n',
            'apply_to_products': False,
        })
        wizard.action_import()
        category.invalidate_recordset()
        self.assertTrue(category.kai_margin_defined)
        self.assertAlmostEqual(category.kai_margin_percent, 15.0)
        self.assertAlmostEqual(category.kai_surcharge, 2.0)
