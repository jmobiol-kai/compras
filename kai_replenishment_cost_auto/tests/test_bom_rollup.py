from odoo import Command
from odoo.tests import tagged

from .common import KaiReplenishmentCommon


@tagged('post_install', '-at_install')
class TestBomRollup(KaiReplenishmentCommon):

    def test_two_levels_recompute_list_price_without_touching_standard_price(self):
        component = self._goods(
            'Masa',
            standard_price=4.0,
            list_price=3.0,
            list_price_type='manual',
            replenishment_cost_type='last_supplier_price',
        )
        semi = self._goods(
            'Disco',
            list_price=1.0,
            list_price_type='by_margin',
            sale_margin=25.0,
            sale_surcharge=10.0,
            replenishment_cost_type='bom',
        )
        finished = self._goods(
            'Empanada',
            list_price=1.0,
            list_price_type='by_margin',
            sale_margin=25.0,
            sale_surcharge=10.0,
            replenishment_cost_type='bom',
        )
        seller = self._shared_seller(component, self.partner_a, 5.0)
        Bom = self.env['mrp.bom']
        Bom.create({
            'product_tmpl_id': semi.product_tmpl_id.id,
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
        Bom.create({
            'product_tmpl_id': finished.product_tmpl_id.id,
            'product_qty': 1.0,
            'product_uom_id': self.uom_unit.id,
            'type': 'normal',
            'company_id': False,
            'bom_line_ids': [Command.create({
                'product_id': semi.id,
                'product_qty': 3.0,
                'product_uom_id': self.uom_unit.id,
            })],
        })

        parents = component.product_tmpl_id._kai_bom_parent_templates()
        self.assertEqual(
            set(parents.ids),
            {semi.product_tmpl_id.id, finished.product_tmpl_id.id},
        )

        bill = self._vendor_bill(self.partner_a, [{
            'product': component,
            'price_unit': 100.0,
        }])
        bill.action_post()

        for record in (component, semi, finished, seller):
            record.invalidate_recordset()

        self.assertAlmostEqual(seller.price, 100.0, places=2)
        self.assertAlmostEqual(component.standard_price, 4.0, places=2)
        self.assertAlmostEqual(component.list_price, 3.0, places=2)
        self.assertEqual(semi.replenishment_cost_type, 'bom')
        self.assertEqual(finished.replenishment_cost_type, 'bom')
        # Disco = 2 x 100. Empanada = 3 x disco. Margen 25% + recargo 10.
        self.assertAlmostEqual(component.replenishment_cost, 100.0, places=2)
        self.assertAlmostEqual(semi.replenishment_cost, 200.0, places=2)
        self.assertAlmostEqual(finished.replenishment_cost, 600.0, places=2)
        self.assertAlmostEqual(semi.list_price, 260.0, places=2)
        self.assertAlmostEqual(finished.list_price, 760.0, places=2)
