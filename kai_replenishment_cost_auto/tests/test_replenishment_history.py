from odoo import Command
from odoo.tests import tagged

from .common import KaiReplenishmentCommon


@tagged('post_install', '-at_install')
class TestReplenishmentHistory(KaiReplenishmentCommon):

    def _rows(self, product, origin='bill'):
        return self.env['kai.replenishment.cost.history'].search([
            ('product_id', '=', product.id),
            ('origin', '=', origin),
        ], order='id asc')

    def test_two_suppliers_same_price_record_two_lines(self):
        product = self._goods(
            'Azúcar',
            list_price=80.0,
            replenishment_cost_type='last_supplier_price',
        )
        other = self.env['res.partner'].create({
            'name': 'Proveedor B',
            'company_id': False,
        })
        first = self._vendor_bill(self.partner_a, [{
            'product': product,
            'price_unit': 100.0,
        }])
        second = self._vendor_bill(other, [{
            'product': product,
            'price_unit': 100.0,
        }])
        first.action_post()
        second.action_post()

        rows = self._rows(product)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].partner_id, self.partner_a)
        self.assertAlmostEqual(rows[0].cost_previous, 0.0, places=2)
        self.assertAlmostEqual(rows[0].cost_new, 100.0, places=2)
        self.assertAlmostEqual(rows[0].variation_amount, 100.0, places=2)
        self.assertEqual(rows[1].partner_id, other)
        self.assertAlmostEqual(rows[1].price_unit, 100.0, places=2)
        self.assertAlmostEqual(rows[1].cost_previous, 100.0, places=2)
        self.assertAlmostEqual(rows[1].cost_new, 100.0, places=2)
        self.assertAlmostEqual(rows[1].variation_amount, 0.0, places=2)
        self.assertAlmostEqual(product.list_price, 80.0, places=2)

        seller = product.seller_ids.filtered(lambda item: not item.company_id and item.partner_id == other)
        self.assertAlmostEqual(seller.price, 100.0, places=2)
        second.button_draft()
        rows.invalidate_recordset()
        self.assertEqual(rows[1].state, 'cancel')
        self.assertEqual(rows[0].state, 'posted')
        seller.invalidate_recordset()
        self.assertAlmostEqual(seller.price, 100.0, places=2)

    def test_bom_cascade_records_parent_without_touching_list_price(self):
        component = self._goods(
            'Masa',
            list_price=4.0,
            replenishment_cost_type='last_supplier_price',
        )
        finished = self._goods(
            'Empanada',
            list_price=15.0,
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
            'price_unit': 50.0,
        }])
        bill.action_post()
        parent_rows = self._rows(finished, origin='bom')
        self.assertEqual(len(parent_rows), 1)
        self.assertEqual(parent_rows.source_product_id, component)
        self.assertEqual(parent_rows.move_id, bill)
        self.assertAlmostEqual(parent_rows.cost_previous, 0.0, places=2)
        self.assertAlmostEqual(parent_rows.cost_new, 100.0, places=2)
        self.assertAlmostEqual(finished.list_price, 15.0, places=2)
        self.assertAlmostEqual(component.list_price, 4.0, places=2)

    def test_backfill_rebuilds_chronological_variation(self):
        product = self._goods(
            'Sal',
            replenishment_cost_type='last_supplier_price',
        )
        other = self.env['res.partner'].create({
            'name': 'Proveedor C',
            'company_id': False,
        })
        first = self._vendor_bill(self.partner_a, [{
            'product': product,
            'price_unit': 40.0,
        }])
        second = self._vendor_bill(other, [{
            'product': product,
            'price_unit': 40.0,
        }])
        first.with_context(kai_skip_replenishment_history=True).action_post()
        second.with_context(kai_skip_replenishment_history=True).action_post()
        self.assertFalse(self._rows(product))

        self.env['kai.replenishment.cost.history'].action_kai_backfill_from_bills()
        rows = self._rows(product)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0].cost_previous, 0.0, places=2)
        self.assertAlmostEqual(rows[0].cost_new, 40.0, places=2)
        self.assertAlmostEqual(rows[1].cost_previous, 40.0, places=2)
        self.assertAlmostEqual(rows[1].cost_new, 40.0, places=2)
        self.assertAlmostEqual(rows[1].variation_amount, 0.0, places=2)
        self.assertEqual(set(rows.mapped('partner_id').ids), {self.partner_a.id, other.id})
