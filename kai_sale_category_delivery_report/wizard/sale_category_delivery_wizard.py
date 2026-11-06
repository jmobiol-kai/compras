import html

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_is_zero

from .allocation_rules import cap_allocation_quantities, plan_purchase, same_company
from .report_rules import (
    commitment_utc_window,
    purchase_order_action_context,
    resolve_tz_name,
    sale_states,
)


class KaiSaleCategoryDeliveryWizard(models.TransientModel):
    _name = 'kai.sale.category.delivery.wizard'
    _description = 'Productos por categoría y fecha de entrega'

    categ_ids = fields.Many2many(
        'product.category',
        string='Categorías',
        required=True,
    )
    delivery_date = fields.Date(
        string='Fecha de entrega',
        required=True,
        help='Día calendario de la fecha de entrega del pedido (commitment_date).',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Proveedor',
        help='Proveedor de la orden de compra. Hay que elegirlo en este '
             'asistente antes de mostrar el informe. No se filtra por supplier_rank.',
    )
    line_ids = fields.One2many(
        'kai.sale.category.delivery.line',
        'wizard_id',
        string='Productos',
    )

    def _tz_name(self):
        self.ensure_one()
        return resolve_tz_name(self.env.user.tz, self.env.company.partner_id.tz)

    def _line_domain(self):
        self.ensure_one()
        start, end = commitment_utc_window(self.delivery_date, self._tz_name())
        return [
            ('order_id.commitment_date', '>=', start),
            ('order_id.commitment_date', '<', end),
            ('order_id.state', 'in', list(sale_states())),
            ('order_id.company_id', '=', self.env.company.id),
            ('display_type', '=', False),
            ('product_id', '!=', False),
            ('product_id.categ_id', 'child_of', self.categ_ids.ids),
        ]

    def _no_demand_error(self):
        return UserError(_(
            'No hay productos de esas categorías en pedidos con fecha de '
            'entrega el %s.',
            self.delivery_date,
        ))

    def _nothing_pending_error(self):
        return UserError(_(
            'No hay cantidades pendientes para comprar. Esas ventas ya están '
            'cubiertas por órdenes de compra; un borrador también cuenta. '
            'Cancelar la compra libera la demanda.'
        ))

    def _sale_lines(self):
        return self.env['sale.order.line'].search(
            self._line_domain(), order='order_id, id',
        )

    def _check_sale_companies(self, sale_lines):
        company_ids = sale_lines.order_id.company_id.ids
        if not same_company(company_ids, self.env.company.id):
            raise UserError(_(
                'El informe mezcla compañías. Genérelo de nuevo con una sola '
                'compañía activa.'
            ))

    def _qty_in_product_uom(self, sale_line):
        product = sale_line.product_id
        qty = sale_line.product_uom_qty
        uom = sale_line.product_uom_id
        if uom and product.uom_id and uom != product.uom_id:
            qty = uom._compute_quantity(
                qty, product.uom_id, rounding_method='HALF-UP',
            )
        return qty

    def _snapshots(self, sale_lines):
        snapshots = []
        for sale_line in sale_lines:
            product = sale_line.product_id
            if not product or sale_line.display_type:
                continue
            if sale_line.order_id.company_id != self.env.company:
                continue
            snapshots.append({
                'sale_line_id': sale_line.id,
                'sale_order_id': sale_line.order_id.id,
                'sale_order_name': sale_line.order_id.name or '',
                'product_id': product.id,
                'qty_demand': self._qty_in_product_uom(sale_line),
                'purchase_ok': bool(product.purchase_ok),
                'default_code': product.default_code or '',
                'product_name': product.with_context(
                    display_default_code=False,
                ).display_name,
                'categ_id': product.categ_id.id,
                'categ_complete_name': product.categ_id.complete_name or '',
                'product_uom_id': product.uom_id.id,
                'rounding': product.uom_id.rounding or 0.01,
            })
        return snapshots

    def _covered_map(self, sale_lines):
        if not sale_lines:
            return {}
        rows = self.env['kai.sale.po.allocation']._read_group(
            [
                ('sale_line_id', 'in', sale_lines.ids),
                ('purchase_state', '!=', 'cancel'),
            ],
            ['sale_line_id'],
            ['quantity:sum'],
        )
        covered = {}
        for sale_line, qty in rows:
            if sale_line:
                covered[sale_line.id] = qty
        return covered

    def _legacy_purchase_orders(self):
        """Purchases labeled for this day that have no coverage rows.

        They are not subtracted from demand. The label is the same text this
        wizard writes on ``origin``; a purchase with any other origin is left
        alone, even if it happens to buy the same products.
        """
        date_str = fields.Date.to_string(self.delivery_date)
        labels = {
            _('Entrega %s', date_str),
            'Entrega %s' % date_str,
        }
        return self.env['purchase.order'].search([
            ('company_id', '=', self.env.company.id),
            ('origin', 'in', list(labels)),
            ('kai_allocation_ids', '=', False),
            ('state', '!=', 'cancel'),
        ])

    def _advisory_lock(self):
        """Serialize generation for this company, day and categories."""
        raw = '%s|%s|%s' % (
            self.env.company.id,
            fields.Date.to_string(self.delivery_date),
            ','.join(str(categ_id) for categ_id in sorted(self.categ_ids.ids)),
        )
        self.env.cr.execute(
            'SELECT pg_advisory_xact_lock(hashtext(%s))',
            (raw,),
        )

    def _store_report(self, rows):
        line_model = self.env['kai.sale.category.delivery.line']
        origin_model = self.env['kai.sale.category.delivery.origin']
        for row in rows:
            line = line_model.create({
                'wizard_id': self.id,
                'product_id': row['product_id'],
                'default_code': row['default_code'],
                'product_name': row['product_name'],
                'categ_id': row['categ_id'],
                'categ_complete_name': row['categ_complete_name'],
                'product_uom_id': row['product_uom_id'],
                'qty_demand': row['qty_demand'],
                'qty_covered': row['qty_covered'],
                'quantity': row['qty_pending'],
                'coverage_state': row['coverage_state'],
                'purchase_ok': row['purchase_ok'],
                'sale_order_ids': [(6, 0, row['sale_order_ids'])],
            })
            origin_model.create([
                {
                    'line_id': line.id,
                    'sale_line_id': origin['sale_line_id'],
                    'sale_order_id': origin['sale_order_id'],
                    'sale_order_name': origin['sale_order_name'],
                    'qty_demand': origin['qty_demand'],
                    'qty_covered': origin['qty_covered'],
                    'qty_pending': origin['qty_pending'],
                    'coverage_state': origin['coverage_state'],
                }
                for origin in row['origins']
            ])

    def action_show(self):
        self.ensure_one()
        if not self.categ_ids:
            raise UserError(_('Seleccione al menos una categoría.'))
        if not self.partner_id:
            raise UserError(_(
                'Seleccione un proveedor antes de mostrar el informe.'
            ))
        self.line_ids.unlink()
        sale_lines = self._sale_lines()
        self._check_sale_companies(sale_lines)
        plan = plan_purchase(self._snapshots(sale_lines), self._covered_map(sale_lines))
        if plan['reason'] == 'empty':
            raise self._no_demand_error()
        self._store_report(plan['rows'])
        list_view = self.env.ref(
            'kai_sale_category_delivery_report.view_kai_sale_category_delivery_line_list'
        )
        search_view = self.env.ref(
            'kai_sale_category_delivery_report.view_kai_sale_category_delivery_line_search'
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Productos por categoría y fecha de entrega'),
            'res_model': 'kai.sale.category.delivery.line',
            'view_mode': 'list',
            'views': [(list_view.id, 'list')],
            'search_view_id': [search_view.id, search_view.name],
            'domain': [('wizard_id', '=', self.id)],
            'target': 'current',
            # edit/create/delete false keep this list read-only. The purchase
            # action must override them: Odoo 19 forwards this context and a
            # false ``edit`` opens the existing PO form read-only.
            'context': {
                'wizard_id': self.id,
                'create': False,
                'edit': False,
                'delete': False,
                'legacy_purchase_ids': self._legacy_purchase_orders().ids,
            },
        }

    def action_create_purchase_order(self):
        """Open one draft purchase order for the vendor chosen on the wizard."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('No hay productos en el informe. Vuelva a generarlo.'))
        if not self.env['purchase.order'].has_access('create'):
            raise UserError(_(
                'No tiene permisos para crear órdenes de compra. '
                'Hace falta el grupo de compras (Usuario).'
            ))
        if not self.partner_id:
            raise UserError(_(
                'Falta el proveedor. Vuelva a abrir el asistente, elija un '
                'proveedor y pulse Mostrar de nuevo antes de generar la orden '
                'de compra.'
            ))
        order = self._create_purchase_order()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Orden de compra'),
            'res_model': 'purchase.order',
            'res_id': order.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            # Standard purchase form (no custom view). These flags override
            # the report's edit=false so a draft PO can edit partner_ref and
            # the company purchase journal. Confirmed-state readonly and
            # multi-company rules stay on the purchase form.
            'context': purchase_order_action_context(),
        }

    def _purchase_qty_uom(self, product, qty_in_product_uom):
        """Quantity and purchase UoM for this vendor.

        Odoo 19 has no ``uom_po_id``. The purchase unit is the vendor pricelist
        unit (``product.supplierinfo.product_uom_id``) when this supplier sells
        the product; otherwise the product unit. The report quantity is in the
        product unit, so it is converted when those units differ.
        """
        seller = product.with_company(self.env.company)._select_seller(
            partner_id=self.partner_id,
            quantity=qty_in_product_uom,
            date=fields.Date.context_today(self),
            uom_id=product.uom_id,
        )
        purchase_uom = product.uom_id
        if seller and seller.product_uom_id:
            purchase_uom = seller.product_uom_id
        qty = product.uom_id._compute_quantity(
            qty_in_product_uom, purchase_uom, rounding_method='HALF-UP',
        )
        return qty, purchase_uom

    def _picking_type_id(self, company):
        """Incoming operation type from the purchase company default.

        ``picking_type_id`` comes from ``purchase_stock`` (installed on this
        client). Without that module the field is absent and the PO is created
        without it.
        """
        order_model = self.env['purchase.order']
        if 'picking_type_id' not in order_model._fields:
            return False
        getter = getattr(order_model, '_get_picking_type', None)
        picking_type = getter(company.id) if getter else order_model._default_picking_type()
        if not picking_type:
            raise UserError(_(
                'No hay un tipo de operación de recepción para la compañía %s.',
                company.display_name,
            ))
        return picking_type.id

    def _create_purchase_order(self):
        """Create one draft PO for the live pending quantity.

        The transient list can be stale after a refresh or a double click.
        Demand is read again under an advisory lock and row locks, and the
        purchase lines are tied to the sale lines by allocation rows in the
        same transaction. ``origin`` stays a date label; it is not coverage.
        """
        self.ensure_one()
        self._advisory_lock()
        allocation_model = self.env['kai.sale.po.allocation']
        sale_lines = self._sale_lines()
        self._check_sale_companies(sale_lines)
        allocation_model.lock_sale_lines(sale_lines)
        locked_ids = set(sale_lines.ids)
        sale_lines = self._sale_lines()
        self._check_sale_companies(sale_lines)
        extra = sale_lines.filtered(lambda line: line.id not in locked_ids)
        if extra:
            allocation_model.lock_sale_lines(extra)
            sale_lines = self._sale_lines()
            self._check_sale_companies(sale_lines)
        plan = plan_purchase(self._snapshots(sale_lines), self._covered_map(sale_lines))
        if plan['reason'] == 'empty':
            raise self._no_demand_error()
        if plan['reason'] == 'covered':
            raise self._nothing_pending_error()
        if plan['reason'] == 'not_purchasable':
            detail = ', '.join(plan['skipped']) or '-'
            raise UserError(_(
                'Ningún producto pendiente se puede comprar. Omitidos: %s',
                detail,
            ))

        products = self.env['product.product'].browse(
            [purchase['product_id'] for purchase in plan['purchases']]
        )
        products_by_id = {product.id: product for product in products}
        ready = []
        rounded_out = []
        for purchase in plan['purchases']:
            product = products_by_id[purchase['product_id']]
            qty, purchase_uom = self._purchase_qty_uom(product, purchase['quantity'])
            if float_is_zero(qty, precision_rounding=purchase_uom.rounding):
                rounded_out.append(purchase['product_name'] or product.display_name)
                continue
            # The purchase unit can round to less than the pending demand.
            # Links must not cover more than this line will actually order.
            ordered_product_qty = purchase_uom._compute_quantity(
                qty, product.uom_id, rounding_method='HALF-UP',
            )
            capped = cap_allocation_quantities(
                [item['quantity'] for item in purchase['allocations']],
                ordered_product_qty,
                purchase['rounding'],
            )
            allocations = []
            for item, quantity in zip(purchase['allocations'], capped):
                if float_is_zero(quantity, precision_rounding=purchase['rounding']):
                    continue
                allocations.append({**item, 'quantity': quantity})
            if not allocations:
                rounded_out.append(purchase['product_name'] or product.display_name)
                continue
            purchase = dict(purchase, allocations=allocations)
            ready.append((product, qty, purchase_uom, purchase))
        if not ready:
            detail = ', '.join(plan['skipped'] + rounded_out) or '-'
            raise UserError(_(
                'Ningún producto pendiente se puede comprar. Omitidos: %s',
                detail,
            ))

        company = self.env.company
        order_model = self.env['purchase.order']
        vals = {
            'partner_id': self.partner_id.id,
            'company_id': company.id,
            'origin': _('Entrega %s', fields.Date.to_string(self.delivery_date)),
        }
        picking_type_id = self._picking_type_id(company)
        if picking_type_id:
            vals['picking_type_id'] = picking_type_id
        order = order_model.create(vals)

        line_model = self.env['purchase.order.line']
        planned = commitment_utc_window(self.delivery_date, self._tz_name())[0]
        line_vals = []
        for product, qty, purchase_uom, _purchase in ready:
            prepared = line_model._prepare_purchase_order_line(
                product, qty, purchase_uom, order.company_id, order.partner_id, order,
            )
            prepared['product_qty'] = qty
            prepared['product_uom_id'] = purchase_uom.id
            prepared['date_planned'] = planned
            line_vals.append(prepared)
        purchase_lines = line_model.create(line_vals)
        # Keep the sale delivery day if a later compute rewrote the schedule.
        # No coverage rows exist yet, so this write does not change links.
        purchase_lines.write({'date_planned': planned})

        allocation_vals = []
        sale_order_ids = set()
        for purchase_line, (_product, _qty, _uom, purchase) in zip(purchase_lines, ready):
            for allocation in purchase['allocations']:
                if float_is_zero(
                    allocation['quantity'],
                    precision_rounding=purchase['rounding'],
                ):
                    continue
                sale_order_ids.add(allocation['sale_order_id'])
                allocation_vals.append({
                    'company_id': company.id,
                    'sale_line_id': allocation['sale_line_id'],
                    'purchase_line_id': purchase_line.id,
                    'purchase_order_id': order.id,
                    'product_id': purchase['product_id'],
                    'product_uom_id': purchase_line.product_id.uom_id.id,
                    'quantity': allocation['quantity'],
                })
        if not allocation_vals:
            raise UserError(_(
                'No se pudo registrar la trazabilidad de la compra. '
                'No se creó la orden.'
            ))
        self.env['kai.sale.po.allocation'].create(allocation_vals)

        notes = []
        skipped = plan['skipped'] + rounded_out
        if skipped:
            notes.append(_(
                'No se incluyeron productos que no se compran: %s',
                ', '.join(skipped),
            ))
        order_names = ', '.join(
            self.env['sale.order'].browse(sorted(sale_order_ids)).mapped('name')
        )
        notes.append(_(
            'Cubre cantidades pendientes de: %s. El detalle está en Ventas origen. '
            'Este borrador ya cuenta como comprometido.',
            order_names,
        ))
        order.message_post(
            body='<br/>'.join(html.escape(note) for note in notes),
            subtype_xmlid='mail.mt_note',
        )
        return order
