from datetime import datetime, time, timedelta

from odoo import models


class ProductSupplierinfo(models.Model):
    _inherit = 'product.supplierinfo'

    def _kai_upsert_shared_seller(self, partner, product, price, currency, invoice_date):
        """Crea o actualiza la tarifa sin compañía de este proveedor y producto.

        El precio queda en la UdM del producto, con descuento 0, porque ya es
        neto. ``product_replenishment_cost`` toma ``net_price`` y, si la tarifa
        tiene una regla, se guarda el precio bruto que la regla necesita para
        que el neto coincida. Una factura con fecha anterior a la de la tarifa
        no pisa un precio más nuevo.

        Devuelve la tarifa escrita, o un recordset vacío si no hubo cambio.
        """
        self = self.sudo()
        template = product.product_tmpl_id.sudo()
        seller = self._kai_shared_seller_for(partner, product)
        if seller and seller.last_date_price_updated and seller.last_date_price_updated.date() > invoice_date:
            return self.browse()

        if template.replenishment_cost_type in ('manual', 'supplier_price'):
            # "Basado en LdM" no se toca: el roll-up sigue mandando.
            template.replenishment_cost_type = 'last_supplier_price'

        rule = seller.replenishment_cost_rule_id
        stored_price = rule.compute_rule_inverse(price) if rule else price
        variant_specific = template.product_variant_count > 1
        vals = {
            'price': stored_price,
            'currency_id': currency.id,
            'product_uom_id': product.uom_id.id,
            'discount': 0.0,
            'company_id': False,
        }
        if seller:
            seller.write(vals)
        else:
            seller = self.with_context(default_company_id=False).create({
                **vals,
                'partner_id': partner.id,
                'product_tmpl_id': template.id,
                'product_id': product.id if variant_specific else False,
                'min_qty': 0.0,
                'delay': 0,
            })
            if seller.company_id:
                seller.company_id = False
        # El compute de Adhoc pisa la fecha con "ahora". La dejamos al final
        # del día de la factura, estrictamente después de otra tarifa del
        # mismo día, para que "último precio" ordene por fecha de factura.
        seller.flush_recordset()
        price_dt = self._kai_invoice_price_datetime(invoice_date, seller)
        self.env.cr.execute(
            "UPDATE product_supplierinfo SET last_date_price_updated = %s WHERE id = %s",
            (price_dt, seller.id),
        )
        seller.invalidate_recordset(['last_date_price_updated'])
        self.env['kai.replenishment.cost.history']._kai_invalidate_cost_cache(product)
        return seller

    def _kai_shared_seller_for(self, partner, product):
        """Tarifa compartida a actualizar: la variante, o la de la plantilla."""
        domain = [
            ('partner_id', '=', partner.id),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('company_id', '=', False),
        ]
        sellers = self.sudo().search(domain)
        if product.product_tmpl_id.product_variant_count > 1:
            specific = sellers.filtered(lambda seller: seller.product_id == product)
            pool = specific
        else:
            template_level = sellers.filtered(lambda seller: not seller.product_id)
            pool = template_level or sellers.filtered(lambda seller: seller.product_id == product)
        if not pool:
            return self.browse()
        return pool.sorted(
            key=lambda seller: seller.last_date_price_updated or datetime.min,
            reverse=True,
        )[:1]

    @staticmethod
    def _kai_invoice_price_datetime(invoice_date, seller):
        end_of_day = datetime.combine(invoice_date, time(23, 59, 59))
        others = seller.product_tmpl_id.seller_ids.filtered(
            lambda other: other.id != seller.id and not other.company_id and other.last_date_price_updated
        )
        same_day = [
            other.last_date_price_updated
            for other in others
            if other.last_date_price_updated.date() == invoice_date
        ]
        if not same_day:
            return end_of_day
        candidate = max(same_day) + timedelta(microseconds=1)
        next_day = datetime.combine(invoice_date + timedelta(days=1), time.min)
        if end_of_day >= candidate:
            return end_of_day
        if candidate < next_day:
            return candidate
        return end_of_day

    def _kai_is_shared_price_winner(self):
        """Esta tarifa compartida es la que usa el último precio del grupo."""
        self.ensure_one()
        if self.company_id or not self.price:
            return False
        shared = self.product_tmpl_id.seller_ids.filtered(
            lambda seller: not seller.company_id and seller.price > 0
        )
        if not shared:
            return False
        winner = shared.sorted(
            key=lambda seller: seller.last_date_price_updated or datetime.min,
            reverse=True,
        )[:1]
        return winner == self
