from datetime import datetime

from odoo import _, api, fields, models
from odoo.tools import float_is_zero


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.depends_context('company')
    @api.depends(
        'seller_ids.net_price',
        'seller_ids.price',
        'seller_ids.currency_id',
        'seller_ids.product_uom_id',
        'seller_ids.company_id',
        'seller_ids.last_date_price_updated',
        'replenishment_cost_type',
    )
    def _compute_supplier_data(self):
        super()._compute_supplier_data()
        # La tarifa compartida (company_id vacío) es el costo único del grupo.
        # Una tarifa de una sucursal no la pisa, aunque su fecha sea posterior:
        # el último precio pagado en cualquier sucursal queda en la compartida.
        for product in self.filtered(lambda item: item.replenishment_cost_type == 'last_supplier_price'):
            shared = product.seller_ids.filtered(lambda seller: not seller.company_id and seller.price > 0)
            if not shared:
                continue
            chosen = shared.sorted(
                key=lambda seller: seller.last_date_price_updated or datetime.min,
                reverse=True,
            )[:1]
            product.update({
                'supplier_price': chosen.net_price or 0.0,
                'supplier_currency_id': chosen.currency_id,
                'supplier_uom_id': chosen.product_uom_id,
            })

    @api.depends_context('company')
    @api.depends(
        'currency_id',
        'supplier_price',
        'supplier_currency_id',
        'supplier_uom_id',
        'uom_id',
        'replenishment_cost_type',
        'replenishment_base_cost',
        'replenishment_base_cost_currency_id',
        'replenishment_cost_rule_id',
        'bom_ids.bom_line_ids.product_qty',
        'bom_ids.bom_line_ids.product_uom_id',
        'seller_ids.price',
        'seller_ids.company_id',
        'product_variant_ids.standard_price',
    )
    def _compute_replenishment_cost(self):
        super()._compute_replenishment_cost()
        # Adhoc deja el costo en 0 si no hay tarifa. Acá se usa el costo
        # contable de la compañía en curso, sin escribirlo de vuelta.
        company = self.env.company
        date = fields.Date.context_today(self)
        for product in self.filtered(
            lambda item: item.replenishment_cost_type in ('supplier_price', 'last_supplier_price')
        ):
            priced = product.seller_ids.filtered(
                lambda seller: (not seller.company_id or seller.company_id == company) and seller.price > 0
            )
            if priced:
                continue
            variant = product.product_variant_ids[:1].with_company(company)
            if not variant:
                continue
            cost = variant.standard_price or 0.0
            src_currency = variant.cost_currency_id or company.currency_id
            if src_currency and product.currency_id and src_currency != product.currency_id:
                cost = src_currency._convert(
                    cost, product.currency_id, company, date, round=False,
                )
            base = cost
            if product.replenishment_cost_rule_id:
                cost = product.replenishment_cost_rule_id.compute_rule(base, product)
            product.replenishment_base_cost_on_currency = base
            product.replenishment_cost = cost

    def _kai_schedule_planned_price_update(self):
        """Recalcula list_price de estos productos y de quienes los usan en LdM.

        ``queue_job`` es opcional: si está instalado, el recálculo queda en
        un job; si no, corre en la misma transacción de la factura.
        """
        templates = self.sudo().exists()
        if not templates:
            return
        if 'queue.job' in self.env.registry:
            templates.with_delay(
                description=_('Actualizar precios de venta por costo de reposición'),
            )._kai_update_planned_prices_from_replenishment()
            return
        templates._kai_update_planned_prices_from_replenishment()

    def _kai_update_planned_prices_from_replenishment(self):
        """Copia el precio planificado (margen de Adhoc) al precio de venta.

        El costo de reposición de Adhoc no está almacenado. Al leer
        ``computed_list_price`` se resuelve el roll-up de la LdM en el momento,
        y ``_update_prices_from_planned`` graba ``list_price``.
        """
        templates = self.sudo()
        affected = templates | templates._kai_bom_parent_templates()
        affected.invalidate_recordset()
        targets = affected.filtered(lambda product: product.list_price_type == 'by_margin')
        if not targets:
            return
        targets.with_context(bypass_base_automation=True)._update_prices_from_planned()
        targets.invalidate_recordset(['list_price'])

    def _kai_bom_parent_templates(self):
        """Plantillas que consumen estos productos, en todos los niveles.

        El conjunto ``seen`` corta los ciclos (un producto que vuelve a
        aparecer no se vuelve a encolar).
        """
        BomLine = self.env['mrp.bom.line'].sudo()
        seen = set(self.ids)
        parents = self.env['product.template']
        frontier = self
        while frontier:
            variants = frontier.with_context(active_test=False).product_variant_ids
            if not variants:
                break
            lines = BomLine.search([('product_id', 'in', variants.ids)])
            nxt = lines.bom_id.product_tmpl_id.filtered(lambda template: template.id not in seen)
            if not nxt:
                break
            parents |= nxt
            seen.update(nxt.ids)
            frontier = nxt
        return parents

    def action_kai_open_zero_replenishment_cost(self):
        """Productos comprables con costo de reposición 0 y sin tarifa > 0.

        Un registro por producto (la tarifa compartida no se parte por
        compañía). El costo se evalúa en la compañía principal, que es la
        que usa el precio planificado.
        """
        precision = self.env['decimal.precision'].precision_get('Product Price')
        main = self.env['res.company']._get_main_company()
        products = self.sudo().with_company(main).search([
            ('purchase_ok', '=', True),
            ('type', '=', 'consu'),
        ])
        priced_ids = set(self.env['product.supplierinfo'].sudo().search([
            ('price', '>', 0),
        ]).product_tmpl_id.ids)
        candidates = products.filtered(lambda product: product.id not in priced_ids)
        candidates.invalidate_recordset(['replenishment_cost'])
        zero_ids = [
            product.id
            for product in candidates.with_company(main)
            if float_is_zero(product.replenishment_cost, precision_digits=precision)
        ]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Productos con costo 0 sin compras'),
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('id', 'in', zero_ids)],
            'context': {'create': False},
            'target': 'current',
        }
