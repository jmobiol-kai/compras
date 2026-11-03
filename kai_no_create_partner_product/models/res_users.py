from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = 'res.users'

    kai_allow_create_partner_product = fields.Boolean(
        string='Permitir creación de productos y contactos desde las cotizaciones',
        default=True,
        help=(
            'Si está marcado, el usuario puede crear contactos y productos desde '
            'cotizaciones de venta y compra, facturas, recibos y pagos. '
            'Si está desmarcado, en esos documentos solo puede elegir registros '
            'que ya existen.'
        ),
    )

    def write(self, vals):
        if (
            'kai_allow_create_partner_product' in vals
            and not self._kai_actor_can_edit_commercial_create_flag()
        ):
            raise AccessError(_(
                'Solo un administrador de permisos puede cambiar '
                '«Permitir creación de productos y contactos desde las cotizaciones».'
            ))
        return super().write(vals)

    def _kai_actor_can_edit_commercial_create_flag(self):
        # ``env.user`` is sudoed, so reading the flag from views and create()
        # does not depend on this check. Writing it does: a user must not be
        # able to turn the permission back on from their own preferences.
        if self.env.su or self.env.uid == SUPERUSER_ID:
            return True
        return self.env.user.has_group('base.group_erp_manager')
