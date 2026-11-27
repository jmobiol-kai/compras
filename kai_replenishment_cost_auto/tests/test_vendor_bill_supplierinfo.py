from datetime import datetime

from odoo import Command, fields
from odoo.tests import tagged

from .common import KaiReplenishmentCommon


@tagged('post_install', '-at_install')
class TestVendorBillSupplierinfo(KaiReplenishmentCommon):

    def test_post_updates_shared_seller_and_ignores_zero_and_refund(self):
        component = self._goods(
            'Harina',
            standard_price=7.0,
            list_price=3.0,
            replenishment_cost_type='last_supplier_price',
        )
        fresh = self._goods('Huevo', replenishment_cost_type='manual')
        gift = self._goods('Muestra', replenishment_cost_type='last_supplier_price')
        seller = self._shared_seller(component, self.partner_a, 50.0)
        contact = self.env['res.partner'].create({
            'name': 'Compras sucursal',
            'parent_id': self.partner_a.id,
            'type': 'invoice',
        })
        self.assertEqual(self.uom_dozen.factor, 12)

        bill = self._vendor_bill(contact, [
            {
                'product': component,
                'quantity': 1.0,
                'uom': self.uom_dozen,
                'price_unit': 120.0,
                'discount': 10.0,
            },
            {
                'product': fresh,
                'quantity': 2.0,
                'price_unit': 30.0,
            },
            {
                'product': gift,
                'quantity': 1.0,
                'price_unit': 0.0,
            },
        ])
        priced = bill.invoice_line_ids.filtered(lambda line: line.product_id == component)
        self.assertAlmostEqual(priced.price_subtotal, 108.0, places=2)

        bill.action_post()

        seller.invalidate_recordset()
        component.invalidate_recordset()
        # 120 con 10% = 108 por docena = 9 por unidad.
        self.assertAlmostEqual(seller.price, 9.0, places=2)
        self.assertFalse(seller.company_id)
        self.assertEqual(seller.partner_id, self.partner_a)
        self.assertEqual(seller.currency_id, self.env.company.currency_id)
        self.assertEqual(seller.product_uom_id, component.uom_id)
        self.assertEqual(seller.discount, 0.0)
        self.assertEqual(seller.last_date_price_updated.date(), bill.invoice_date)
        self.assertEqual(
            self.env['product.supplierinfo'].search_count([
                ('product_tmpl_id', '=', component.product_tmpl_id.id),
                ('company_id', '=', False),
            ]),
            1,
        )
        self.assertAlmostEqual(component.standard_price, 7.0, places=2)
        self.assertAlmostEqual(component.list_price, 3.0, places=2)

        created = self.env['product.supplierinfo'].search([
            ('product_tmpl_id', '=', fresh.product_tmpl_id.id),
            ('partner_id', '=', self.partner_a.id),
            ('company_id', '=', False),
        ])
        self.assertEqual(len(created), 1)
        self.assertAlmostEqual(created.price, 30.0, places=2)
        self.assertEqual(fresh.product_tmpl_id.replenishment_cost_type, 'last_supplier_price')

        self.assertFalse(self.env['product.supplierinfo'].search([
            ('product_tmpl_id', '=', gift.product_tmpl_id.id),
        ]))

        refund = self.env['account.move'].create({
            'move_type': 'in_refund',
            'partner_id': self.partner_a.id,
            'invoice_date': bill.invoice_date,
            'invoice_line_ids': [Command.create({
                'product_id': component.id,
                'name': component.name,
                'quantity': 1.0,
                'price_unit': 1.0,
                'tax_ids': [Command.clear()],
            })],
        })
        refund.invoice_line_ids.write({'price_unit': 1.0, 'tax_ids': [Command.clear()]})
        refund.action_post()
        seller.invalidate_recordset()
        self.assertAlmostEqual(seller.price, 9.0, places=2)

        bill.button_draft()
        seller.invalidate_recordset()
        self.assertAlmostEqual(seller.price, 9.0, places=2)

    def test_older_bill_does_not_overwrite_a_newer_price(self):
        product = self._goods('Aceite', replenishment_cost_type='last_supplier_price')
        seller = self._shared_seller(product, self.partner_a, 40.0)
        # Fecha fija, posterior a la factura. No depende de "ahora" ni del
        # orden de creación si dos tarifas empatan el día.
        self.env.cr.execute(
            "UPDATE product_supplierinfo SET last_date_price_updated = %s WHERE id = %s",
            (datetime(2026, 6, 1, 12, 0, 0), seller.id),
        )
        self.env['kai.replenishment.cost.history']._kai_invalidate_cost_cache(product)

        bill = self._vendor_bill(self.partner_a, [{
            'product': product,
            'price_unit': 1.0,
        }], invoice_date=fields.Date.to_date('2026-01-15'))
        bill.action_post()
        seller.invalidate_recordset()
        self.assertAlmostEqual(seller.price, 40.0, places=2)

    def test_without_seller_replenishment_falls_back_to_standard_price(self):
        product = self._goods(
            'Sin compras',
            standard_price=15.0,
            replenishment_cost_type='last_supplier_price',
        )
        product.invalidate_recordset()
        self.assertAlmostEqual(product.replenishment_cost, 15.0, places=2)

        self._shared_seller(product, self.partner_a, 4.0)
        product.invalidate_recordset()
        self.assertAlmostEqual(product.replenishment_cost, 4.0, places=2)

    def test_zero_cost_action_lists_unsold_without_tariff(self):
        missing = self._goods('Sin tarifa', standard_price=0.0, replenishment_cost_type='last_supplier_price')
        valued = self._goods('Con costo contable', standard_price=8.0, replenishment_cost_type='last_supplier_price')
        bought = self._goods('Con tarifa', replenishment_cost_type='last_supplier_price')
        self._shared_seller(bought, self.partner_a, 6.0)
        service = self.env['product.product'].create({
            'name': 'Servicio',
            'type': 'service',
            'purchase_ok': True,
            'standard_price': 0.0,
        })

        action = self.env['product.template'].action_kai_open_zero_replenishment_cost()
        ids = set(action['domain'][0][2])
        self.assertIn(missing.product_tmpl_id.id, ids)
        self.assertNotIn(valued.product_tmpl_id.id, ids)
        self.assertNotIn(bought.product_tmpl_id.id, ids)
        self.assertNotIn(service.product_tmpl_id.id, ids)
