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
            replenishment_cost_type='last_supplier_price',
        )
        semi = self._goods(
            'Disco',
            list_price=11.0,
            replenishment_cost_type='bom',
        )
        finished = self._goods(
            'Empanada',
            list_price=12.0,
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
        self.assertAlmostEqual(semi.list_price, 11.0, places=2)
        self.assertAlmostEqual(finished.list_price, 12.0, places=2)
        self.assertEqual(semi.replenishment_cost_type, 'bom')
        self.assertEqual(finished.replenishment_cost_type, 'bom')
        # Disco = 2 x 100. Empanada = 3 x disco. El precio de venta no se toca.
        self.assertAlmostEqual(component.replenishment_cost, 100.0, places=2)
        self.assertAlmostEqual(semi.replenishment_cost, 200.0, places=2)
        self.assertAlmostEqual(finished.replenishment_cost, 600.0, places=2)
