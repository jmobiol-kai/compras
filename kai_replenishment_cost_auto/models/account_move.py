from odoo import fields, models
from odoo.tools import float_compare


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        res = super().action_post()
        # Solo facturas de proveedor publicadas. Las notas de crédito
        # (in_refund) no bajan el costo: un reembolso no es "el último
        # precio pagado". Volver a borrador o cancelar tampoco revierte
        # la tarifa (no hay hook en button_draft / button_cancel).
        self.filtered(
            lambda move: move.state == 'posted' and move.move_type == 'in_invoice'
        )._kai_update_replenishment_from_vendor_bill()
        return res

    def _kai_update_replenishment_from_vendor_bill(self):
        """Crea o actualiza la tarifa compartida.

        No escribe ``standard_price`` ni ``list_price``.
        """
        precision = self.env['decimal.precision'].precision_get('Product Price')
        Supplier = self.env['product.supplierinfo']
        for move in self:
            partner = move.commercial_partner_id
            invoice_date = move.invoice_date or move.date
            company_currency = move.company_id.currency_id
            if not partner or not invoice_date or not company_currency:
                continue
            # La última línea con precio > 0 de cada producto gana.
            chosen = {}
            lines = move.invoice_line_ids.sorted(key=lambda line: (line.sequence, line.id or 0))
            for line in lines:
                if not line._kai_replenishment_price_line():
                    continue
                price = line._kai_net_unit_price_product_uom(company_currency)
                if float_compare(price, 0.0, precision_digits=precision) <= 0:
                    continue
                chosen[line.product_id] = price
            for product, price in chosen.items():
                Supplier._kai_upsert_shared_seller(
                    partner, product, price, company_currency, invoice_date,
                )


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _kai_replenishment_price_line(self):
        """Línea de producto de una factura de proveedor, con cantidad."""
        self.ensure_one()
        if self.display_type != 'product' or not self.product_id:
            return False
        if self.move_id.move_type != 'in_invoice':
            return False
        if 'is_downpayment' in self._fields and self.is_downpayment:
            return False
        uom = self.product_uom_id or self.product_id.uom_id
        return bool(uom) and not uom.is_zero(self.quantity)

    def _kai_net_unit_price_product_uom(self, to_currency):
        """Precio unitario neto (descuento aplicado, sin IVA) en la UdM del producto.

        ``price_subtotal`` ya es el importe sin impuestos y con el descuento
        de la línea, en la moneda de la factura. Se pasa a la UdM del producto
        y después a ``to_currency`` (moneda de la compañía que publica).
        """
        self.ensure_one()
        quantity = self.quantity or 0.0
        if not quantity:
            return 0.0
        net_line_uom = (self.price_subtotal or 0.0) / quantity
        line_uom = self.product_uom_id or self.product_id.uom_id
        net_product_uom = line_uom._compute_price(net_line_uom, self.product_id.uom_id)
        move = self.move_id
        if move.currency_id and to_currency and move.currency_id != to_currency:
            net_product_uom = move.currency_id._convert(
                net_product_uom,
                to_currency,
                move.company_id,
                move.invoice_date or move.date or fields.Date.context_today(self),
                round=False,
            )
        return to_currency.round(net_product_uom) if to_currency else net_product_uom
