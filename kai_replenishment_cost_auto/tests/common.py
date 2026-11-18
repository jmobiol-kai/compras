from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class KaiReplenishmentCommon(AccountTestInvoicingCommon):

    def _goods(self, name, **extra):
        vals = {
            'name': name,
            'type': 'consu',
            'is_storable': True,
            'purchase_ok': True,
            'sale_ok': True,
            'uom_id': self.uom_unit.id,
            'taxes_id': [Command.clear()],
            'supplier_taxes_id': [Command.clear()],
            'standard_price': 0.0,
            'list_price': 1.0,
        }
        vals.update(extra)
        product = self.env['product.product'].create(vals)
        # account crea el producto y, si no tiene compañía, le agrega el
        # impuesto por defecto de las otras compañías. Uno con precio
        # incluido (IVA 21%) cambia el precio planificado. Se dejan vacíos.
        product.write({
            'taxes_id': [Command.clear()],
            'supplier_taxes_id': [Command.clear()],
        })
        return product

    def _shared_seller(self, product, partner, price):
        return self.env['product.supplierinfo'].create({
            'partner_id': partner.id,
            'product_tmpl_id': product.product_tmpl_id.id,
            'price': price,
            'currency_id': self.env.company.currency_id.id,
            'company_id': False,
            'product_uom_id': product.uom_id.id,
            'discount': 0.0,
            'min_qty': 0.0,
        })

    def _vendor_bill(self, partner, lines, invoice_date=None):
        """Factura de proveedor. El precio se escribe después del alta.

        El compute de ``price_unit`` pisa el valor si viaja en el mismo
        create que el producto. Un segundo write, sin cambiar el producto,
        deja el precio y el descuento que pasamos.
        """
        invoice_date = invoice_date or fields.Date.context_today(self)
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': invoice_date,
            'invoice_line_ids': [
                Command.create({
                    'product_id': spec['product'].id,
                    'name': spec['product'].display_name,
                    'quantity': spec.get('quantity', 1.0),
                    'price_unit': 1.0,
                    'tax_ids': [Command.clear()],
                })
                for spec in lines
            ],
        })
        bill.invoice_date = invoice_date
        for line, spec in zip(bill.invoice_line_ids, lines):
            if spec.get('uom'):
                line.write({
                    'product_uom_id': spec['uom'].id,
                    'quantity': spec.get('quantity', 1.0),
                })
            line.write({
                'price_unit': spec['price_unit'],
                'discount': spec.get('discount', 0.0),
                'quantity': spec.get('quantity', 1.0),
                'tax_ids': [Command.clear()],
            })
        return bill
