from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

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

    def action_show(self):
        self.ensure_one()
        if not self.categ_ids:
            raise UserError(_('Seleccione al menos una categoría.'))
        if not self.partner_id:
            raise UserError(_(
                'Seleccione un proveedor antes de mostrar el informe.'
            ))
        self.line_ids.unlink()
        groups = self.env['sale.order.line']._read_group(
            self._line_domain(),
            ['product_id', 'product_uom_id'],
            ['product_uom_qty:sum'],
        )
        totals = {}
        for product, uom, qty in groups:
            if not product:
                continue
            if uom and uom != product.uom_id:
                qty = uom._compute_quantity(
                    qty, product.uom_id, rounding_method='HALF-UP',
                )
            totals[product] = totals.get(product, 0.0) + qty
        if not totals:
            raise UserError(_(
                'No hay productos de esas categorías en pedidos con fecha de '
                'entrega el %s.',
                self.delivery_date,
            ))

        vals_list = []
        for product, qty in totals.items():
            rounding = product.uom_id.rounding or 0.01
            qty = float_round(qty, precision_rounding=rounding)
            vals_list.append({
                'wizard_id': self.id,
                'product_id': product.id,
                'default_code': product.default_code or '',
                'product_name': product.with_context(
                    display_default_code=False,
                ).display_name,
                'categ_id': product.categ_id.id,
                'categ_complete_name': product.categ_id.complete_name or '',
                'product_uom_id': product.uom_id.id,
                'quantity': qty,
                'purchase_ok': bool(product.purchase_ok),
            })
        self.env['kai.sale.category.delivery.line'].create(vals_list)
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
        self.ensure_one()
        order_model = self.env['purchase.order']
        commands_ready = []
        skipped = []
        for line in self.line_ids:
            product = line.product_id
            if not product.purchase_ok:
                skipped.append(product.display_name)
                continue
            if float_compare(line.quantity, 0.0, precision_rounding=product.uom_id.rounding) <= 0:
                continue
            qty, purchase_uom = self._purchase_qty_uom(product, line.quantity)
            if float_is_zero(qty, precision_rounding=purchase_uom.rounding):
                continue
            commands_ready.append((product, qty, purchase_uom))
        if not commands_ready:
            detail = ', '.join(skipped) if skipped else '-'
            raise UserError(_(
                'Ningún producto del listado se puede comprar. Omitidos: %s',
                detail,
            ))

        company = self.env.company
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
        for product, qty, purchase_uom in commands_ready:
            prepared = line_model._prepare_purchase_order_line(
                product, qty, purchase_uom, order.company_id, order.partner_id, order,
            )
            prepared['product_qty'] = qty
            prepared['product_uom_id'] = purchase_uom.id
            prepared['date_planned'] = planned
            line_vals.append(prepared)
        lines = line_model.create(line_vals)
        # Keep the sale delivery day if a later compute rewrote the schedule.
        lines.write({'date_planned': planned})

        if skipped:
            order.message_post(
                body=_(
                    'No se incluyeron productos que no se compran: %s',
                    ', '.join(skipped),
                ),
                subtype_xmlid='mail.mt_note',
            )
        return order
