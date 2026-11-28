# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import api, models

# Códigos con los que l10n_latam_check da de alta cheques (new_check).
# Si al confirmar el método ya no es uno de estos, action_post borra
# l10n_latam_new_check_ids. Hay que preferirlos antes que «la primera línea».
_KAI_NEW_CHECK_CODES = ('own_checks', 'new_third_party_checks')


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def _kai_has_new_latam_checks(self):
        """El pago tiene cheques nuevos que action_post podría borrar."""
        self.ensure_one()
        if 'l10n_latam_new_check_ids' not in self._fields:
            return False
        return bool(self.l10n_latam_new_check_ids)

    def _kai_available_method_lines(self, journal, payment_type=None):
        """Líneas del diario destino para este tipo de pago.

        Si el diario ya es el del pago, se usa el campo calculado: ahí ya
        están aplicadas las exclusiones de ``_get_payment_method_codes_to_exclude``.
        Si el diario todavía no se escribió (viene en vals), se consultan
        las líneas de ese diario y se filtran las exclusiones.
        """
        lines = self.env['account.payment.method.line']
        if not journal:
            return lines
        payment = self[:1] if len(self) == 1 else self.browse()
        payment_type = payment_type or (payment.payment_type if payment else False) or 'inbound'
        if payment and payment.journal_id == journal and payment.payment_type == payment_type:
            return payment.available_payment_method_line_ids
        lines = journal._get_available_payment_method_lines(payment_type)
        if payment:
            excluded = payment._get_payment_method_codes_to_exclude()
            if excluded:
                lines = lines.filtered(lambda line: line.code not in excluded)
        return lines

    @api.model
    def _kai_method_needs_sync(self, method_line, journal, available):
        """La línea no sirve para este diario y hay que reasignarla.

        Una línea sin diario (métodos que no cuelgan de un diario) se deja.
        La que ya es del diario destino y está entre las disponibles, también.
        """
        if not method_line or not journal:
            return False
        if not method_line.journal_id:
            return False
        if method_line.journal_id == journal and method_line.id in available.ids:
            return False
        return True

    def _kai_sync_payment_method_line_to_journal(
        self, method_line=None, journal=None, payment_type=None, prefer_checks=None,
    ):
        """Línea de método que corresponde al diario destino.

        No crea diarios, líneas ni cuentas. Sin diario, devuelve un recordset
        vacío para que el llamador no toque el pago.

        Orden: el mismo ``payment_method_id``; si no, el mismo código y un
        ``payment_type`` compatible; si hay cheques (o el origen era un alta
        de cheques), una línea ``own_checks`` o ``new_third_party_checks`` del
        mismo subtipo; si no, la primera disponible.
        """
        payment = self[:1] if len(self) == 1 else self.browse()
        line_model = self.env['account.payment.method.line']
        if method_line is None:
            method_line = payment.payment_method_line_id if payment else line_model
        if method_line:
            method_line = method_line._origin
        if journal is None and payment:
            journal = payment.journal_id
        if not journal:
            return line_model

        payment_type = payment_type or (payment.payment_type if payment else False) or 'inbound'
        if prefer_checks is None:
            prefer_checks = bool(payment and payment._kai_has_new_latam_checks())

        available = self._kai_available_method_lines(journal, payment_type)
        if method_line and (
            not method_line.journal_id
            or (method_line.journal_id == journal and method_line.id in available.ids)
        ):
            return method_line

        if method_line and method_line.payment_method_id:
            same_method = available.filtered(
                lambda line: line.payment_method_id == method_line.payment_method_id
            )[:1]
            if same_method:
                return same_method

        origin_code = method_line.code if method_line else False
        if origin_code:
            same_code = available.filtered(
                lambda line: (
                    line.code == origin_code
                    and line.payment_method_id.payment_type == payment_type
                )
            )[:1]
            if same_code:
                return same_code

        # Mismo subtipo de alta (own_checks o new_third_party_checks) antes
        # de caer a Transferencia: si no, action_post de l10n_latam_check
        # borra los cheques.
        if prefer_checks or origin_code in _KAI_NEW_CHECK_CODES:
            if origin_code in _KAI_NEW_CHECK_CODES:
                same_subtype = available.filtered(lambda line: line.code == origin_code)[:1]
                if same_subtype:
                    return same_subtype
            check_lines = available.filtered(lambda line: line.code in _KAI_NEW_CHECK_CODES)
            if check_lines:
                return check_lines[:1]

        return available[:1]

    def _kai_assign_method_line(self, line_id):
        """Escribe la línea ya mapeada, sin volver a entrar en el write."""
        self.ensure_one()
        if self.state != 'draft':
            return
        if self.payment_method_line_id.id == (line_id or False):
            return
        self.with_context(
            kai_skip_method_journal_sync=True,
            kai_keep_payment_method_line=True,
        ).write({'payment_method_line_id': line_id or False})

    def _kai_fix_draft_methods_after_write(self):
        """Red de seguridad si el cómputo no llegó a alinear el método.

        Solo borradores. Un pago ya confirmado no se reescribe.
        """
        for payment in self.filtered(lambda pay: pay.state == 'draft'):
            origin = payment.payment_method_line_id
            journal = payment.journal_id
            available = payment._kai_available_method_lines(journal, payment.payment_type)
            if not payment._kai_method_needs_sync(origin, journal, available):
                continue
            mapped = payment._kai_sync_payment_method_line_to_journal(
                method_line=origin,
                journal=journal,
            )
            payment._kai_assign_method_line(mapped.id if mapped else False)

    @api.model
    def _kai_vals_have_new_checks(self, vals):
        commands = vals.get('l10n_latam_new_check_ids')
        if not commands or 'l10n_latam_new_check_ids' not in self._fields:
            return False
        for command in commands:
            if command and command[0] in (0, 1, 4):
                return True
        return False

    @api.model
    def _kai_sync_create_vals(self, vals):
        """Reemplaza en vals un método de otro diario. Devuelve True si lo cambió.

        El constraint de core corre dentro de ``super().create``. Hay que
        dejar el id correcto antes de llamarlo.
        """
        if not vals.get('payment_method_line_id') or not vals.get('journal_id'):
            return False
        journal = self.env['account.journal'].browse(vals['journal_id'])
        origin = self.env['account.payment.method.line'].browse(vals['payment_method_line_id'])
        payment_type = vals.get('payment_type') or 'inbound'
        available = journal._get_available_payment_method_lines(payment_type)
        if not self._kai_method_needs_sync(origin, journal, available):
            return False
        mapped = self._kai_sync_payment_method_line_to_journal(
            method_line=origin,
            journal=journal,
            payment_type=payment_type,
            prefer_checks=self._kai_vals_have_new_checks(vals),
        )
        new_id = mapped.id if mapped else False
        if new_id == (origin.id or False):
            return False
        vals['payment_method_line_id'] = new_id
        return True

    def _kai_prepare_write_vals(self, vals):
        """Ajusta ``payment_method_line_id`` antes de ``super().write``.

        Devuelve ``(vals, pendientes)``. ``pendientes`` es una lista
        ``(pago, id de línea)`` cuando un solo vals no alcanza (cada pago
        cae en una línea distinta). El cambio de diario solo, sin método en
        vals, lo resuelve el cómputo.
        """
        if 'payment_method_line_id' not in vals:
            return vals, []

        line_model = self.env['account.payment.method.line']
        journal_model = self.env['account.journal']
        resolved = []
        needs_any = False
        for payment in self:
            if vals.get('journal_id'):
                journal = journal_model.browse(vals['journal_id'])
            else:
                journal = payment.journal_id
            if vals.get('payment_method_line_id'):
                origin = line_model.browse(vals['payment_method_line_id'])
            else:
                origin = line_model
            payment_type = vals.get('payment_type') or payment.payment_type
            available = payment._kai_available_method_lines(journal, payment_type)
            if payment._kai_method_needs_sync(origin, journal, available):
                needs_any = True
                mapped = payment._kai_sync_payment_method_line_to_journal(
                    method_line=origin,
                    journal=journal,
                    payment_type=payment_type,
                )
                line_id = mapped.id if mapped else False
            else:
                line_id = origin.id if origin else False
            resolved.append((payment, line_id))

        if not needs_any:
            return vals, []

        line_ids = {line_id for _payment, line_id in resolved}
        if len(line_ids) == 1:
            vals['payment_method_line_id'] = next(iter(line_ids))
            return vals, []

        # Diarios distintos: el mismo id no sirve para todos. Se saca del
        # vals, se escribe el resto y después se asigna cada línea.
        vals.pop('payment_method_line_id', None)
        return vals, resolved

    @api.depends('available_payment_method_line_ids')
    def _compute_payment_method_line_id(self):
        """Mapea el método del diario anterior antes del default del partner.

        El cómputo de core, si el id actual no está entre las líneas del
        diario nuevo, usa el default del partner o la primera disponible.
        Nunca busca ``own_checks`` en el diario nuevo: por eso «Cheques
        propios» de Mercado Pago pasaba a «Transferencia» de Santander, o
        quedaba el id viejo si el formulario lo reenviaba.

        El default del partner sigue valiendo en un pago nuevo sin método,
        y cuando la línea ya es del diario actual.
        """
        keep_explicit = self.env.context.get('kai_keep_payment_method_line')
        standard = self.browse()
        for pay in self:
            current = pay.payment_method_line_id
            if current:
                current = current._origin
            journal = pay.journal_id
            available = pay.available_payment_method_line_ids
            if current and not current.journal_id:
                pay.payment_method_line_id = current
                continue
            if pay._kai_method_needs_sync(current, journal, available):
                pay.payment_method_line_id = pay._kai_sync_payment_method_line_to_journal(
                    method_line=current,
                    journal=journal,
                )
                continue
            if keep_explicit and current and current.id in available.ids:
                # El write ya dejó la línea mapeada. No dejar que el default
                # del partner la pise en el mismo flush.
                pay.payment_method_line_id = current
                continue
            standard |= pay
        if standard:
            super(AccountPayment, standard)._compute_payment_method_line_id()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('kai_skip_method_journal_sync'):
            changed = False
            for vals in vals_list:
                if self._kai_sync_create_vals(vals):
                    changed = True
            if changed:
                self = self.with_context(kai_keep_payment_method_line=True)
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('kai_skip_method_journal_sync'):
            return super().write(vals)

        # Copiamos vals: account_payment_pro también lo muta (amount_exact,
        # quick_edit_mode). El constraint de core compara
        # payment_method_line_id.journal_id con payment.journal_id y solo
        # está declarado sobre el método. Si el write trae el diario nuevo
        # y la línea del diario viejo, falla dentro de super() antes de
        # cualquier arreglo posterior.
        vals = dict(vals)
        pending = []
        keep = False
        drafts_only = bool(self) and all(pay.state == 'draft' for pay in self)
        if drafts_only:
            vals, pending = self._kai_prepare_write_vals(vals)
            keep = 'payment_method_line_id' in vals and not pending and (
                'journal_id' in vals or 'payment_type' in vals
                or any(
                    pay.payment_method_line_id.id != vals.get('payment_method_line_id')
                    for pay in self
                )
            )
        records = self.with_context(kai_keep_payment_method_line=True) if keep else self
        result = super(AccountPayment, records).write(vals)
        if pending:
            for payment, line_id in pending:
                payment = payment.exists()
                if payment and payment.state == 'draft':
                    payment._kai_assign_method_line(line_id)
        elif drafts_only or any(pay.state == 'draft' for pay in self):
            self._kai_fix_draft_methods_after_write()
        return result

    def action_post(self):
        """Alinea el método de los borradores y recién ahí confirma.

        Un pago guardado con el diario nuevo y la línea del diario anterior
        (el caso del pago 2440) dispara el constraint al confirmar. Se
        corrige antes de ``super()`` para que ``l10n_latam_check`` vea
        ``own_checks`` y no borre los cheques.
        """
        if not self.env.context.get('kai_skip_method_journal_sync'):
            for payment in self.filtered(lambda pay: pay.state == 'draft'):
                origin = payment.payment_method_line_id
                journal = payment.journal_id
                available = payment._kai_available_method_lines(journal, payment.payment_type)
                if not payment._kai_method_needs_sync(origin, journal, available):
                    continue
                mapped = payment._kai_sync_payment_method_line_to_journal(
                    method_line=origin,
                    journal=journal,
                )
                payment._kai_assign_method_line(mapped.id if mapped else False)
        return super().action_post()
