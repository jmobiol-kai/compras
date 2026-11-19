from datetime import datetime

from odoo import _, api, fields, models
from odoo.tools import float_is_zero


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # En product_replenishment_cost_mrp 19.0.1.0.0 (el que va con
    # product_replenishment_cost 19.0.1.3.0) el costo no es recursive.
    # Sin esto, al calcular en lote el ORM devuelve 0 para el componente
    # que está en el mismo batch. 19.0.1.2.0 de Adhoc ya lo marca; repetirlo
    # no cambia columnas.
    replenishment_cost = fields.Float(recursive=True)
    replenishment_base_cost_on_currency = fields.Float(recursive=True)
    kai_own_margin = fields.Boolean(
        string='Margen propio',
        help=(
            'Si está marcado, el precio planificado usa el margen y el recargo '
            'de este producto. Si no, usa los de la categoría (heredados del padre '
            'cuando la categoría no define los suyos).'
        ),
    )
    kai_category_margin_percent = fields.Float(
        string='Margen de la categoría %',
        related='categ_id.kai_effective_margin_percent',
        digits='Discount',
    )
    kai_category_surcharge = fields.Float(
        string='Recargo de la categoría',
        related='categ_id.kai_effective_surcharge',
        digits='Product Price',
    )

    @api.depends_context('company')
    @api.depends(
        'seller_ids.net_price',
        'seller_ids.price',
        'seller_ids.currency_id',
        'seller_ids.company_id',
        'seller_ids.last_date_price_updated',
        'replenishment_cost_type',
    )
    def _compute_supplier_data(self):
        super()._compute_supplier_data()
        # La tarifa compartida (company_id vacío) es el costo único del grupo.
        # Una tarifa de una sucursal no la pisa, aunque su fecha sea posterior.
        # supplier_uom_id existe recién en product_replenishment_cost 19.0.1.7.0.
        # En 19.0.1.3.0 el costo usa supplier_price tal cual, y nosotros lo
        # guardamos ya en la UdM del producto.
        has_supplier_uom = 'supplier_uom_id' in self._fields
        for product in self.filtered(lambda item: item.replenishment_cost_type == 'last_supplier_price'):
            shared = product.seller_ids.filtered(lambda seller: not seller.company_id and seller.price > 0)
            if not shared:
                continue
            chosen = shared.sorted(
                key=lambda seller: seller.last_date_price_updated or datetime.min,
                reverse=True,
            )[:1]
            values = {
                'supplier_price': chosen.net_price or 0.0,
                'supplier_currency_id': chosen.currency_id,
            }
            if has_supplier_uom:
                values['supplier_uom_id'] = chosen.product_uom_id
            product.update(values)

    @api.depends_context('company')
    @api.depends(
        'currency_id',
        'supplier_price',
        'supplier_currency_id',
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
        # standard_price es company_dependent (jsonb). El cómputo de Adhoc
        # corre con compute_sudo y, leído por el ORM en otra compañía, devuelve
        # 0. Se toma la clave de la compañía en curso directo de la base.
        accounting_costs = self._kai_standard_price_by_template(company)
        for product in self.filtered(
            lambda item: item.replenishment_cost_type in ('supplier_price', 'last_supplier_price')
        ):
            priced = product.seller_ids.filtered(
                lambda seller: (not seller.company_id or seller.company_id == company) and seller.price > 0
            )
            if priced:
                continue
            variant = product.product_variant_ids[:1]
            if not variant:
                continue
            cost = accounting_costs.get(product.id, 0.0)
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

    def _kai_effective_margin(self):
        """Margen y recargo que arman el precio: el del producto o el de la categoría."""
        self.ensure_one()
        if self.kai_own_margin:
            return self.sale_margin or 0.0, self.sale_surcharge or 0.0
        category = self.categ_id
        if not category:
            return 0.0, 0.0
        return category.kai_effective_margin_percent or 0.0, category.kai_effective_surcharge or 0.0

    def _kai_price_with_included_taxes(self, price):
        """Suma el IVA incluido, igual que el precio planificado de Adhoc."""
        self.ensure_one()
        included = self.taxes_id.filtered('price_include')
        if not included:
            return price
        return included.compute_all(
            price,
            self.currency_id,
            product=self,
            handle_price_include=False,
        )['total_included']

    @api.depends(
        'kai_own_margin',
        'categ_id.kai_effective_margin_percent',
        'categ_id.kai_effective_surcharge',
    )
    def _compute_computed_list_price(self):
        """«Por margen» sin margen propio usa el margen efectivo de la categoría.

        La fórmula es la de Adhoc: costo de reposición de la compañía principal
        (en este cliente, Blinis SA) × (1 + margen %) + recargo, y el IVA si el
        impuesto está incluido en el precio. Con margen propio se dejan los
        campos sale_margin y sale_surcharge.
        """
        from_category = self.filtered(
            lambda product: product.list_price_type == 'by_margin' and not product.kai_own_margin
        )
        super(ProductTemplate, self - from_category)._compute_computed_list_price()
        for product in from_category:
            margin, surcharge = product._kai_effective_margin()
            price = product.replenishment_cost_main_company * (1.0 + margin / 100.0) + surcharge
            product.computed_list_price = product._kai_price_with_included_taxes(price)

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

    def _kai_standard_price_by_template(self, company):
        """Costo contable (standard_price) de la compañía, por plantilla.

        El campo es jsonb ``{id_compañía: importe}``. Un ORM con sudo o con
        otra compañía en el contexto devuelve el fallback 0.
        """
        variants = self.with_context(active_test=False).product_variant_ids
        if not variants or not company:
            return {}
        variants.flush_recordset(['standard_price'])
        self.env.cr.execute(
            """
            SELECT product_tmpl_id,
                   COALESCE(MAX((standard_price ->> %s)::numeric), 0)
              FROM product_product
             WHERE id IN %s
             GROUP BY product_tmpl_id
            """,
            (str(company.id), tuple(variants.ids)),
        )
        return {template_id: float(amount or 0.0) for template_id, amount in self.env.cr.fetchall()}

    def _kai_template_ids_with_any_standard_price(self):
        """Plantillas con costo contable > 0 en alguna compañía."""
        variants = self.with_context(active_test=False).product_variant_ids
        if not variants:
            return set()
        variants.flush_recordset(['standard_price'])
        self.env.cr.execute(
            """
            SELECT DISTINCT pp.product_tmpl_id
              FROM product_product pp
              CROSS JOIN LATERAL jsonb_each(
                  COALESCE(pp.standard_price, '{}'::jsonb)
              ) AS kv(key, value)
             WHERE pp.id IN %s
               AND jsonb_typeof(kv.value) = 'number'
               AND (kv.value #>> '{}')::numeric > 0
            """,
            (tuple(variants.ids),),
        )
        return {row[0] for row in self.env.cr.fetchall()}

    def action_kai_open_zero_replenishment_cost(self):
        """Productos comprables con costo de reposición 0 y sin tarifa > 0.

        Un registro por producto. El costo contable es por compañía: si
        cualquier sucursal tiene ``standard_price`` > 0, el producto no entra.
        Un fabricado entra solo si el roll-up es 0 en todas las compañías.
        """
        precision = self.env['decimal.precision'].precision_get('Product Price')
        products = self.sudo().search([
            ('purchase_ok', '=', True),
            ('type', '=', 'consu'),
        ])
        priced_ids = set(self.env['product.supplierinfo'].sudo().search([
            ('price', '>', 0),
            ('product_tmpl_id', 'in', products.ids),
        ]).product_tmpl_id.ids) if products else set()
        candidates = products.filtered(lambda product: product.id not in priced_ids)
        with_accounting_cost = candidates._kai_template_ids_with_any_standard_price()
        candidates = candidates.filtered(lambda product: product.id not in with_accounting_cost)
        companies = self.env['res.company'].sudo().search([])
        zero_ids = []
        for product in candidates:
            if product.replenishment_cost_type != 'bom':
                zero_ids.append(product.id)
                continue
            has_rollup = any(
                not float_is_zero(
                    product.with_company(company).replenishment_cost,
                    precision_digits=precision,
                )
                for company in companies
            )
            if not has_rollup:
                zero_ids.append(product.id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Productos con costo 0 sin compras'),
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('id', 'in', zero_ids)],
            'context': {'create': False},
            'target': 'current',
        }
