from odoo import api, fields, models

from .kai_no_create import user_can_create_partner_product


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Kept so existing code can still read the permission. It follows the
    # security group (and Settings administrators), it is not edited by hand.
    kai_allow_create_partner_product = fields.Boolean(
        string='Puede crear productos y contactos en cualquier pantalla',
        compute='_compute_kai_allow_create_partner_product',
        search='_search_kai_allow_create_partner_product',
        help=(
            'Verdadero si el usuario tiene el permiso '
            '«Puede crear productos y contactos en cualquier pantalla» '
            'o es administrador. En ese caso puede crear contactos y productos '
            'desde cualquier pantalla. Si no, solo desde Inventario y Contactos.'
        ),
    )

    @api.depends('all_group_ids')
    def _compute_kai_allow_create_partner_product(self):
        for user in self:
            user.kai_allow_create_partner_product = user_can_create_partner_product(user)

    def _search_kai_allow_create_partner_product(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError(
                'kai_allow_create_partner_product does not support %s' % operator
            )
        wanted = bool(value)
        if operator == '!=':
            wanted = not wanted
        group_ids = [
            self.env.ref('kai_no_create_partner_product.group_kai_allow_create_partner_product').id,
            self.env.ref('base.group_system').id,
        ]
        domain = [('all_group_ids', 'in', group_ids)]
        if wanted:
            return domain
        return [('all_group_ids', 'not in', group_ids)]
