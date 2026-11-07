import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare, float_is_zero

from ..wizard.allocation_rules import cap_allocation_quantities
from ..wizard.report_rules import purchase_order_action_context

CONSUMIDOR_FINAL_NAME = 'Consumidor Final Anónimo'
CONSUMIDOR_FINAL_XMLID = 'l10n_ar.par_cfa'


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    kai_allocation_ids = fields.One2many(
        'kai.sale.po.allocation',
        'purchase_order_id',
        string='Cobertura de ventas',
        copy=False,
    )
    kai_sale_order_count = fields.Integer(
        string='Ventas origen',
        compute='_compute_kai_sale_order_count',
    )

    @api.depends('kai_allocation_ids.sale_order_id')
    def _compute_kai_sale_order_count(self):
        for order in self:
            order.kai_sale_order_count = len(order.kai_allocation_ids.sale_order_id)

    def action_view_kai_source_sales(self):
        self.ensure_one()
        orders = self.kai_allocation_ids.sale_order_id
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Ventas origen'),
            'res_model': 'sale.order',
            'domain': [('id', 'in', orders.ids)],
            'target': 'current',
            # The report list is not editable. Opening a sale from here must
            # not inherit that flag; the sale form keeps its own readonly.
            'context': purchase_order_action_context(),
        }
        if len(orders) == 1:
            action.update({
                'view_mode': 'form',
                'views': [(False, 'form')],
                'res_id': orders.id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')],
            })
        return action

    def action_kai_undo_sale_trace(self):
        """Cancel, drop this report's links and lines, and return to draft.

        The purchase order and its number stay, so the sequence is not
        consumed. Sale orders are not deleted. A normal cancellation does
        not call this: it keeps the lines and the links. Only a purchase
        user, and only while the order still has links from this report,
        can run it. Confirmed orders, done receipts, vendor bills and
        payments are refused. The emptied draft can be filled and confirmed
        again; that does not restore the old links.
        """
        self.ensure_one()
        self._kai_check_undo_access()
        self._kai_check_undo_allowed()
        # Resolve before any cancel, unlink or draft. A missing or ambiguous
        # contact aborts the whole transaction.
        consumer = self._kai_consumidor_final_partner()
        allocation_model = self.env['kai.sale.po.allocation']
        allocation_model.lock_sale_lines(self.kai_allocation_ids.sale_line_id)
        self._kai_check_undo_allowed()
        consumer = self._kai_consumidor_final_partner()
        sale_names = ', '.join(self.kai_allocation_ids.sale_order_id.mapped('name'))
        partner_ref = self.partner_ref
        name = self.name
        if self.state in ('draft', 'sent'):
            self.button_cancel()
        self.kai_allocation_ids.unlink()
        self.order_line.unlink()
        self.button_draft()
        if self._kai_origin_is_report_label(self.origin):
            self.origin = False
        self.partner_id = consumer
        self.with_company(self.company_id).onchange_partner_id()
        if self.partner_ref != partner_ref:
            self.partner_ref = partner_ref
        if self.partner_id != consumer or self.partner_ref != partner_ref or self.name != name:
            raise UserError(_(
                'No se pudo deshacer sin conservar el número y la referencia de proveedor.'
            ))
        self.message_post(
            body=_(
                'Se anuló y deshizo la cotización %(name)s. '
                'Se quitaron los productos y los vínculos con %(sales)s. '
                'La orden volvió a borrador con el mismo número. '
                'El proveedor pasó a %(partner)s. '
                'La referencia de proveedor no se modificó. '
                'Las ventas no se borraron y la demanda quedó libre.',
                name=name,
                sales=sale_names or '-',
                partner=consumer.display_name,
            ),
            subtype_xmlid='mail.mt_note',
        )
        return True

    def _kai_consumidor_final_partner(self):
        """The one Consumidor Final Anónimo this company may use.

        Prefers the official ``l10n_ar.par_cfa`` record when that module
        created it, the user can read it, and it belongs to this purchase
        company or to every company. Otherwise requires exactly one active
        partner with that exact name in the same scope. Does not create
        contacts and does not use a partial name match.
        """
        self.ensure_one()
        company = self.company_id
        official = self._kai_official_consumidor_final(company)
        if official:
            return official
        partners = self.env['res.partner'].search([
            ('name', '=', CONSUMIDOR_FINAL_NAME),
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ])
        if len(partners) == 1:
            return partners
        if not partners:
            raise UserError(_(
                'No hay un contacto activo «%(name)s» visible para la compañía %(company)s. '
                'No se deshizo la orden.',
                name=CONSUMIDOR_FINAL_NAME,
                company=company.display_name,
            ))
        raise UserError(_(
            'Hay más de un contacto «%(name)s» para la compañía %(company)s. '
            'No se deshizo la orden.',
            name=CONSUMIDOR_FINAL_NAME,
            company=company.display_name,
        ))

    def _kai_official_consumidor_final(self, company):
        partner = self.env.ref(CONSUMIDOR_FINAL_XMLID, raise_if_not_found=False)
        if not partner:
            return self.env['res.partner']
        try:
            partner.check_access('read')
            applicable = (
                partner.active
                and partner.name == CONSUMIDOR_FINAL_NAME
                and (not partner.company_id or partner.company_id == company)
            )
        except AccessError:
            return self.env['res.partner']
        return partner if applicable else self.env['res.partner']

    def _kai_check_undo_access(self):
        if not self.env.user.has_group('purchase.group_purchase_user'):
            raise UserError(_(
                'Solo un usuario de compras puede anular y deshacer la cotización.'
            ))
        self.check_access('write')
        self.env['purchase.order.line'].check_access('unlink')
        self.env['kai.sale.po.allocation'].check_access('unlink')

    def _kai_check_undo_allowed(self):
        self.ensure_one()
        if self.state not in ('draft', 'sent', 'cancel'):
            raise UserError(_(
                'Solo se puede anular y deshacer una cotización en borrador, '
                'enviada o cancelada. %(name)s está en estado %(state)s.',
                name=self.name,
                state=dict(self._fields['state']._description_selection(self.env)).get(self.state, self.state),
            ))
        if self.locked:
            raise UserError(_(
                'La orden %(name)s está bloqueada. Desbloquéela antes de deshacerla.',
                name=self.name,
            ))
        if not self.kai_allocation_ids:
            raise UserError(_(
                'Esta orden no tiene vínculos de ventas del informe. '
                'No se deshace una compra ajena ni una que ya fue deshecha.'
            ))
        invoices = self.invoice_ids.filtered(lambda move: move.state != 'cancel')
        if invoices:
            labels = [move.name or move.display_name or str(move.id) for move in invoices]
            raise UserError(_(
                'No se deshace %(name)s porque tiene facturas de proveedor: %(bills)s.',
                name=self.name,
                bills=', '.join(labels),
            ))
        paid = self.invoice_ids.filtered(
            lambda move: move.payment_state not in ('not_paid', 'invoicing_legacy', False)
            and move.state != 'cancel'
        )
        if paid:
            raise UserError(_(
                'No se deshace %(name)s porque tiene pagos registrados.',
                name=self.name,
            ))
        if 'picking_ids' in self._fields:
            done_pickings = self.picking_ids.filtered(lambda picking: picking.state == 'done')
            if done_pickings:
                raise UserError(_(
                    'No se deshace %(name)s porque tiene recepciones hechas: %(pickings)s.',
                    name=self.name,
                    pickings=', '.join(done_pickings.mapped('name')),
                ))
        if 'move_ids' in self.env['purchase.order.line']._fields:
            done_moves = self.order_line.move_ids.filtered(lambda move: move.state == 'done')
            if done_moves:
                raise UserError(_(
                    'No se deshace %(name)s porque tiene movimientos de stock hechos.',
                    name=self.name,
                ))

    @api.model
    def _kai_origin_is_report_label(self, origin):
        """True only for the exact delivery label this report writes."""
        text = (origin or '').strip()
        match = re.fullmatch(r'(.+) (\d{4}-\d{2}-\d{2})', text)
        if not match:
            return False
        date_text = match.group(2)
        return text in {
            _('Entrega %s', date_text),
            'Entrega %s' % date_text,
        }


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    kai_allocation_ids = fields.One2many(
        'kai.sale.po.allocation',
        'purchase_line_id',
        string='Cobertura de ventas',
        copy=False,
    )

    def write(self, vals):
        tracked = {'product_id', 'product_qty', 'product_uom_id'} & set(vals)
        if not tracked:
            return super().write(vals)
        products_before = {line.id: line.product_id.id for line in self}
        res = super().write(vals)
        self._kai_sync_allocations(products_before)
        return res

    def _kai_sync_allocations(self, products_before):
        """Keep links equal to what this line still buys.

        A smaller quantity, or a unit that converts to less, drops coverage
        from the newest sale line backward. A larger quantity does not cover
        more sale demand. A different product drops the links; the demand
        becomes pending again and this line is no longer tied to those sales.
        """
        allocs = self.kai_allocation_ids
        if not allocs:
            return
        Allocation = self.env['kai.sale.po.allocation']
        Allocation.lock_sale_lines(allocs.sale_line_id)
        for line in self:
            line_allocs = line.kai_allocation_ids.sorted(key=lambda alloc: alloc.id)
            if not line_allocs:
                continue
            product_changed = products_before.get(line.id) != line.product_id.id
            linked_products = line_allocs.product_id
            if product_changed or linked_products != line.product_id:
                line_allocs.unlink()
                continue
            cap = line.product_uom_id._compute_quantity(
                line.product_qty,
                line.product_id.uom_id,
                rounding_method='HALF-UP',
            )
            rounding = line.product_id.uom_id.rounding or 0.01
            new_quantities = cap_allocation_quantities(
                [alloc.quantity for alloc in line_allocs], cap, rounding,
            )
            to_unlink = Allocation.browse()
            for alloc, quantity in zip(line_allocs, new_quantities):
                if float_is_zero(quantity, precision_rounding=rounding):
                    to_unlink |= alloc
                elif float_compare(alloc.quantity, quantity, precision_rounding=rounding) != 0:
                    alloc.quantity = quantity
            to_unlink.unlink()
