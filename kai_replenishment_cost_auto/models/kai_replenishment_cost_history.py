from odoo import _, api, fields, models
from odoo.tools import float_compare, float_is_zero


class KaiReplenishmentCostHistory(models.Model):
    _name = 'kai.replenishment.cost.history'
    _description = 'Historial de costo de reposición'
    _order = 'date desc, id desc'
    _rec_name = 'product_id'

    date = fields.Date(string='Fecha', required=True, index=True)
    product_id = fields.Many2one(
        'product.product', string='Producto', required=True, index=True, ondelete='cascade',
    )
    product_tmpl_id = fields.Many2one(
        'product.template', string='Plantilla', required=True, index=True, ondelete='cascade',
    )
    categ_id = fields.Many2one(
        'product.category', string='Categoría', related='product_tmpl_id.categ_id', store=True,
    )
    partner_id = fields.Many2one('res.partner', string='Proveedor', index=True)
    company_id = fields.Many2one(
        'res.company', string='Sucursal', required=True, index=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Moneda', required=True,
        help='Moneda de la compañía principal. Los importes del historial están en esa moneda.',
    )
    move_id = fields.Many2one('account.move', string='Factura', index=True, ondelete='set null')
    move_line_id = fields.Many2one(
        'account.move.line', string='Línea de factura', index=True, ondelete='set null',
    )
    quantity = fields.Float(string='Cantidad', digits='Product Unit')
    product_uom_id = fields.Many2one('uom.uom', string='UdM')
    price_unit = fields.Monetary(
        string='Precio unitario',
        currency_field='currency_id',
        help='Precio neto de la línea, en la unidad del producto y en la moneda de la compañía principal.',
    )
    cost_previous = fields.Monetary(string='Costo anterior', currency_field='currency_id')
    cost_new = fields.Monetary(string='Costo nuevo', currency_field='currency_id')
    variation_amount = fields.Monetary(string='Variación', currency_field='currency_id')
    variation_percent = fields.Float(string='Variación %', digits='Discount')
    origin = fields.Selection(
        [('bill', 'Factura'), ('bom', 'LdM')],
        string='Origen', required=True, default='bill', index=True,
    )
    source_product_id = fields.Many2one(
        'product.product', string='Componente',
        help='En una fila de lista de materiales, el insumo comprado que disparó el cambio.',
    )
    state = fields.Selection(
        [('posted', 'Vigente'), ('cancel', 'Anulada')],
        string='Estado', required=True, default='posted', index=True,
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS kai_repl_cost_history_product_state_date_idx
            ON kai_replenishment_cost_history (product_id, state, date DESC, id DESC)
            """
        )

    def _kai_invalidate_cost_cache(self, products):
        """Tira la caché de la tarifa y del costo en todos los entornos del cursor.

        ``seller_ids`` y ``net_price`` quedan viejos si se leyeron antes de
        crear o actualizar la tarifa. Sin esto el costo nuevo repite el
        anterior (o queda en 0) aunque la tarifa ya se haya escrito.
        """
        products = self.env['product.product'].browse(products.ids)
        if not products:
            return
        templates = products.product_tmpl_id
        sellers = self.env['product.supplierinfo'].sudo().search([
            ('product_tmpl_id', 'in', templates.ids),
        ])
        seller_fields = [
            name for name in (
                'net_price', 'price', 'discount', 'currency_id',
                'last_date_price_updated', 'product_uom_id', 'company_id',
            )
            if name in sellers._fields
        ]
        template_fields = [
            name for name in (
                'seller_ids', 'replenishment_cost', 'supplier_price',
                'supplier_currency_id', 'replenishment_base_cost_on_currency',
                'supplier_uom_id',
            )
            if name in templates._fields
        ]
        product_fields = [
            name for name in ('replenishment_cost', 'seller_ids', 'variant_seller_ids')
            if name in products._fields
        ]
        targets = []
        envs = getattr(self.env.transaction, 'envs', None)
        if envs:
            targets = list(envs)
        if self.env not in targets:
            targets.append(self.env)
        for env in targets:
            if sellers and seller_fields:
                env['product.supplierinfo'].browse(sellers.ids).invalidate_recordset(seller_fields)
            if template_fields:
                env['product.template'].browse(templates.ids).invalidate_recordset(template_fields)
            if product_fields:
                env['product.product'].browse(products.ids).invalidate_recordset(product_fields)

    def _kai_cost_in_main_currency(self, product, main, date):
        """Costo de reposición de un solo producto, en la moneda principal.

        El prefetch queda en ese producto. Si el fabricado entra en el mismo
        lote, Adhoc devuelve 0 para el componente que todavía se está
        calculando y la cascada no ve el cambio.
        """
        self.env['product.supplierinfo'].flush_model()
        self._kai_invalidate_cost_cache(product)
        product = self.env['product.product'].browse(product.id).sudo().with_company(main)
        product = product.with_prefetch(product._ids)
        cost = product.replenishment_cost or 0.0
        currency = product.currency_id
        target = main.currency_id
        if currency and target and currency != target:
            cost = currency._convert(cost, target, main, date, round=False)
        return target.round(cost) if target else cost

    def _kai_variation(self, previous, new):
        amount = new - previous
        if float_is_zero(previous, precision_digits=6):
            percent = 0.0 if float_is_zero(new, precision_digits=6) else 100.0
        else:
            percent = amount / previous * 100.0
        return amount, percent

    @api.model
    def _kai_prepare_common(self, product, main, date, move, line, origin, source=None):
        return {
            'date': date,
            'product_id': product.id,
            'product_tmpl_id': product.product_tmpl_id.id,
            'partner_id': move.commercial_partner_id.id,
            'company_id': move.company_id.id,
            'currency_id': main.currency_id.id,
            'move_id': move.id,
            'move_line_id': line.id,
            'quantity': line.quantity,
            'product_uom_id': (line.product_uom_id or product.uom_id).id,
            'origin': origin,
            'source_product_id': source.id if source else False,
            'state': 'posted',
        }

    @api.model
    def _kai_register_bill_line(self, line, price_main):
        """Una fila por línea de factura, y la cascada de LdM si el costo cambia.

        No escribe ``list_price`` ni ``standard_price``.
        """
        self = self.sudo()
        move = line.move_id
        product = line.product_id
        main = self.env['res.company']._get_main_company()
        date = move.invoice_date or move.date
        parents = list(product.product_tmpl_id._kai_bom_parent_products())
        previous_cost = self._kai_cost_in_main_currency(product, main, date)
        # No se lee el costo del fabricado acá: si entra en el mismo lote que
        # el insumo, Adhoc devuelve 0 y la fila de LdM no se crea. El roll-up
        # usa el costo del insumo (anterior y nuevo) y el del resto de hojas.
        base_costs = {}
        for parent in parents:
            self._kai_seed_bom_leaves(parent, base_costs, main, date, {product.id})
        self.env['product.supplierinfo']._kai_upsert_shared_seller(
            move.commercial_partner_id,
            product,
            price_main,
            main.currency_id,
            date,
        )
        # El costo anterior ya quedó leído. El nuevo se lee ahora, con la
        # tarifa escrita y la caché vaciada.
        self.env['product.supplierinfo'].flush_model()
        product.product_tmpl_id.flush_recordset()
        self._kai_invalidate_cost_cache(product)
        new_cost = self._kai_cost_in_main_currency(product, main, date)
        variation, percent = self._kai_variation(previous_cost, new_cost)
        rows = [dict(
            self._kai_prepare_common(product, main, date, move, line, 'bill'),
            price_unit=price_main,
            cost_previous=previous_cost,
            cost_new=new_cost,
            variation_amount=variation,
            variation_percent=percent,
        )]
        if parents and float_compare(new_cost, previous_cost, precision_digits=6) != 0:
            # La clave es el id (int). dict(..., **{id: valor}) exige strings.
            previous_running = dict(base_costs)
            previous_running[product.id] = previous_cost
            new_running = dict(base_costs)
            new_running[product.id] = new_cost
            for parent in parents:
                parent_prev = self._kai_simulated_bom_cost(parent, previous_running)
                parent_new = self._kai_simulated_bom_cost(parent, new_running)
                if float_compare(parent_new, parent_prev, precision_digits=6) == 0:
                    continue
                parent_var, parent_pct = self._kai_variation(parent_prev, parent_new)
                rows.append(dict(
                    self._kai_prepare_common(
                        parent, main, date, move, line, 'bom', source=product,
                    ),
                    price_unit=price_main,
                    cost_previous=parent_prev,
                    cost_new=parent_new,
                    variation_amount=parent_var,
                    variation_percent=parent_pct,
                ))
        return self.create(rows)

    def _kai_seed_bom_leaves(self, product, running, main, date, skip_ids, seen=None):
        """Costos actuales de los insumos que esta factura no está cambiando."""
        template = product.product_tmpl_id
        seen = set(seen or ())
        if template.id in seen:
            return
        if template.replenishment_cost_type != 'bom':
            if product.id not in skip_ids and product.id not in running:
                running[product.id] = self._kai_cost_in_main_currency(product, main, date)
            return
        seen.add(template.id)
        bom = self.env['mrp.bom'].sudo()._bom_find(product)[product]
        if not bom:
            if product.id not in skip_ids and product.id not in running:
                running[product.id] = self._kai_cost_in_main_currency(product, main, date)
            return
        for bom_line in bom.bom_line_ids:
            self._kai_seed_bom_leaves(
                bom_line.product_id, running, main, date, skip_ids, seen,
            )

    def _kai_void_for_moves(self, moves):
        """Marca anuladas las filas de esas facturas. No toca la tarifa ni el costo."""
        rows = self.sudo().search([
            ('move_id', 'in', moves.ids),
            ('state', '=', 'posted'),
        ])
        rows.write({'state': 'cancel'})
        return rows

    @api.model
    def action_kai_backfill_from_bills(self):
        """Arma el historial con las facturas de proveedor ya publicadas.

        El costo anterior sale del orden de las facturas, no del costo de hoy.
        No modifica tarifas ni precios de venta.
        """
        precision = self.env['decimal.precision'].precision_get('Product Price')
        main = self.env['res.company'].sudo()._get_main_company()
        moves = self.env['account.move'].sudo().search([
            ('state', '=', 'posted'),
            ('move_type', '=', 'in_invoice'),
        ], order='invoice_date asc, id asc')
        existing_lines = set(self.sudo().search([
            ('origin', '=', 'bill'),
            ('state', '=', 'posted'),
            ('move_line_id', '!=', False),
        ]).mapped('move_line_id').ids)
        existing_bom = {
            (row.move_line_id.id, row.product_id.id)
            for row in self.sudo().search([
                ('origin', '=', 'bom'),
                ('state', '=', 'posted'),
                ('move_line_id', '!=', False),
            ])
        }
        running = {}
        last_date = {}
        created = 0
        for move in moves:
            date = move.invoice_date or move.date
            if not date or not move.commercial_partner_id:
                continue
            lines = move.invoice_line_ids.sorted(key=lambda item: (item.sequence, item.id or 0))
            for line in lines:
                if not line._kai_replenishment_price_line():
                    continue
                price = line._kai_net_unit_price_product_uom(main.currency_id)
                if float_compare(price, 0.0, precision_digits=precision) <= 0:
                    continue
                product = line.product_id
                previous = running.get(product.id, 0.0)
                applies = product.id not in last_date or date >= last_date[product.id]
                new_cost = price if applies else previous
                if applies:
                    last_date[product.id] = date
                    running[product.id] = new_cost
                if line.id not in existing_lines:
                    variation, percent = self._kai_variation(previous, new_cost)
                    self.sudo().create(dict(
                        self._kai_prepare_common(product, main, date, move, line, 'bill'),
                        price_unit=price,
                        cost_previous=previous,
                        cost_new=new_cost,
                        variation_amount=variation,
                        variation_percent=percent,
                    ))
                    created += 1
                    existing_lines.add(line.id)
                if float_compare(new_cost, previous, precision_digits=precision) == 0:
                    continue
                for parent in product.product_tmpl_id._kai_bom_parent_products():
                    parent_new = self._kai_simulated_bom_cost(parent, running)
                    parent_prev = running.get(parent.id, 0.0)
                    running[parent.id] = parent_new
                    if (line.id, parent.id) in existing_bom:
                        continue
                    if float_compare(parent_new, parent_prev, precision_digits=precision) == 0:
                        continue
                    parent_var, parent_pct = self._kai_variation(parent_prev, parent_new)
                    self.sudo().create(dict(
                        self._kai_prepare_common(
                            parent, main, date, move, line, 'bom', source=product,
                        ),
                        price_unit=price,
                        cost_previous=parent_prev,
                        cost_new=parent_new,
                        variation_amount=parent_var,
                        variation_percent=parent_pct,
                    ))
                    created += 1
                    existing_bom.add((line.id, parent.id))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Historial de costo'),
                'message': _('Se cargaron %s filas desde facturas publicadas.', created),
                'type': 'success',
                'sticky': False,
            },
        }

    def _kai_simulated_bom_cost(self, product, running, seen=None):
        """Roll-up con los costos ya recorridos, para el backfill."""
        template = product.product_tmpl_id
        if template.replenishment_cost_type != 'bom':
            return running.get(product.id, 0.0)
        seen = set(seen or ())
        if template.id in seen:
            return running.get(product.id, 0.0)
        seen.add(template.id)
        bom = self.env['mrp.bom'].sudo()._bom_find(product)[product]
        if not bom:
            return 0.0
        total = 0.0
        for bom_line in bom.bom_line_ids:
            component = bom_line.product_id
            if component.product_tmpl_id.replenishment_cost_type == 'bom':
                component_cost = self._kai_simulated_bom_cost(component, running, seen)
            else:
                component_cost = running.get(component.id, 0.0)
            quantity = bom_line.product_uom_id._compute_quantity(
                bom_line.product_qty, component.uom_id,
            )
            total += component_cost * quantity
        if bom.product_qty:
            total = bom.product_uom_id._compute_price(total / bom.product_qty, product.uom_id)
        currency = self.env['res.company']._get_main_company().currency_id
        return currency.round(total) if currency else total
