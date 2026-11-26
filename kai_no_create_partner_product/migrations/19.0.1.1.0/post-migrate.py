"""Give the new group to users who were explicitly allowed, and drop the old form."""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_TABLE = 'kai_nocreate_pp_allowed_user'


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _drop_legacy_user_form(env)
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM information_schema.tables
             WHERE table_schema = 'public'
               AND table_name = %s
        )
        """,
        (_TABLE,),
    )
    if not cr.fetchone()[0]:
        return
    cr.execute("SELECT user_id FROM %s" % _TABLE)
    user_ids = [row[0] for row in cr.fetchall()]
    cr.execute("DROP TABLE %s" % _TABLE)
    if not user_ids:
        return
    group = env.ref(
        'kai_no_create_partner_product.group_kai_allow_create_partner_product'
    )
    users = env['res.users'].browse(user_ids).exists()
    if users:
        users.write({'group_ids': [(4, group.id)]})
    _logger.info(
        "kai_no_create_partner_product: upgrade from %s assigned %s to %s user(s).",
        version,
        group.name,
        len(users),
    )


def _drop_legacy_user_form(env):
    data = env['ir.model.data'].search([
        ('module', '=', 'kai_no_create_partner_product'),
        ('name', '=', 'view_users_form_kai_allow_create'),
    ])
    if not data:
        return
    views = env['ir.ui.view'].browse(data.mapped('res_id')).exists()
    if views:
        views.unlink()
    data.unlink()
