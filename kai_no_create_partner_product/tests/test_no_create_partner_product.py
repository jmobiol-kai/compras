# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import ast
import importlib.util
import os

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

import odoo.addons.kai_no_create_partner_product as kai_no_create_partner_product
from odoo.addons.kai_no_create_partner_product.models.kai_no_create import (
    CONTEXT_KEY,
    inject_context_key,
    merge_no_create_options,
)

# Fields whose many2one target is a contact or a product. A guarded screen
# must lock every occurrence, including the ones embedded in one2many lines.
LOCKED_FIELD_NAMES = (
    'partner_id',
    'partner_invoice_id',
    'partner_shipping_id',
    'vendor_id',
    'product_id',
    'product_tmpl_id',
)

GUARDED_MODELS = (
    'sale.order',
    'sale.order.line',
    'purchase.order',
    'purchase.order.line',
    'account.move',
    'account.move.line',
    'account.payment',
    'purchase.requisition',
    'mrp.bom',
    'mrp.bom.line',
    'mrp.production',
    'stock.picking',
    'stock.move',
    'stock.move.line',
    'stock.warehouse.orderpoint',
    'stock.scrap',
    'product.pricelist.item',
    'account.bank.statement.line',
    'pos.order',
    'pos.order.line',
)


@tagged('post_install', '-at_install')
class TestKaiNoCreatePartnerProduct(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group = cls.env.ref(
            'kai_no_create_partner_product.group_kai_allow_create_partner_product'
        )
        xmlids = [
            'base.group_partner_manager',
            'product.group_product_manager',
            'product.group_product_variant',
            'sales_team.group_sale_salesman',
            'purchase.group_purchase_user',
            'account.group_account_invoice',
            'mrp.group_mrp_user',
            'point_of_sale.group_pos_user',
        ]
        cls.operational_groups = cls.env['res.groups']
        for xmlid in xmlids:
            cls.operational_groups |= cls.env.ref(xmlid)
        cls.blocked = cls._create_user('kai_blocked_create', cls.operational_groups)
        cls.allowed = cls._create_user(
            'kai_allowed_create',
            cls.operational_groups | cls.group,
        )
        cls.admin_user = cls._create_user(
            'kai_admin_exempt',
            cls.env.ref('base.group_system'),
        )
        cls.env.flush_all()
        cls.env.registry.clear_cache()

    @classmethod
    def _create_user(cls, login, groups):
        return cls.env['res.users'].with_context(
            no_reset_password=True,
            mail_create_nosubscribe=True,
            tracking_disable=True,
        ).create({
            'name': login,
            'login': login,
            'email': '%s@example.com' % login,
            'group_ids': [(4, group.id) for group in groups],
        })

    def test_group_replaces_the_user_boolean(self):
        group = self.group.with_context(lang='en_US')
        self.assertEqual(
            group.name,
            'Puede crear productos y contactos en cualquier pantalla',
        )
        self.assertEqual(
            group.privilege_id.category_id,
            self.env.ref('base.module_category_hidden'),
        )
        self.assertIn(self.env.ref('base.group_system'), group.implied_by_ids)

        self.assertFalse(self.blocked.kai_allow_create_partner_product)
        self.assertTrue(self.allowed.kai_allow_create_partner_product)
        self.assertTrue(self.admin_user.kai_allow_create_partner_product)
        self.assertTrue(self.admin_user.has_group(
            'kai_no_create_partner_product.group_kai_allow_create_partner_product'
        ))
        self.assertFalse(self.blocked.has_group('base.group_system'))

        found = self.env['res.users'].search([
            ('kai_allow_create_partner_product', '=', True),
            ('id', 'in', (self.blocked | self.allowed | self.admin_user).ids),
        ])
        self.assertEqual(found, self.allowed | self.admin_user)

    def test_upgrade_migration_clears_existing_users(self):
        user = self._create_user('kai_no_create_upgrade', self.env['res.groups'])
        self.env.flush_all()
        cr = self.env.cr
        cr.execute(
            """
            ALTER TABLE res_users
            ADD COLUMN IF NOT EXISTS kai_allow_create_partner_product boolean
            """
        )
        cr.execute(
            """
            UPDATE res_users
               SET kai_allow_create_partner_product = TRUE
             WHERE id = %s
            """,
            (user.id,),
        )
        migrate = self._load_migration('19.0.1.0.2', 'post-migrate.py', 'kai_old_post')
        migrate(cr, None)
        self.assertTrue(self._flag_column(user.id))
        migrate(cr, '19.0.1.0.1')
        self.assertFalse(self._flag_column(user.id))

    def test_group_migration_keeps_users_allowed_after_19_0_1_0_2(self):
        user = self._create_user('kai_was_allowed', self.env['res.groups'])
        self.env.flush_all()
        cr = self.env.cr
        cr.execute(
            """
            ALTER TABLE res_users
            ADD COLUMN IF NOT EXISTS kai_allow_create_partner_product boolean
            """
        )
        cr.execute(
            """
            UPDATE res_users
               SET kai_allow_create_partner_product = TRUE
             WHERE id = %s
            """,
            (user.id,),
        )
        pre = self._load_migration('19.0.1.1.0', 'pre-migrate.py', 'kai_pre')
        pre(cr, '19.0.1.0.1')
        self.assertFalse(self._migration_table_exists())

        pre(cr, '19.0.1.0.2')
        cr.execute("SELECT user_id FROM kai_nocreate_pp_allowed_user")
        self.assertIn(user.id, [row[0] for row in cr.fetchall()])

        cr.execute("ALTER TABLE res_users DROP COLUMN kai_allow_create_partner_product")
        post = self._load_migration('19.0.1.1.0', 'post-migrate.py', 'kai_post')
        post(cr, '19.0.1.0.2')
        self.env.registry.clear_cache()
        user.invalidate_recordset()
        self.assertTrue(user.has_group(
            'kai_no_create_partner_product.group_kai_allow_create_partner_product'
        ))
        self.assertTrue(user.kai_allow_create_partner_product)

    def test_create_from_requisition_bom_and_picking_follows_the_group(self):
        cases = (
            ('purchase.requisition', 'product_id', 'product.product'),
            ('mrp.bom', 'product_id', 'product.product'),
            ('stock.picking', 'product_id', 'product.product'),
            ('stock.picking', 'partner_id', 'res.partner'),
        )
        for model, field_name, target in cases:
            context = self._literal_context(model, field_name)
            self.assertTrue(context.get(CONTEXT_KEY), '%s.%s' % (model, field_name))
            target_model = self.env[target].with_user(self.allowed).with_context(context)
            if target == 'res.partner':
                created = target_model.create({'name': 'Permitido %s' % model})
                quick = target_model.name_create('Rapido %s' % model)
            else:
                created = target_model.create({'name': 'Permitido %s %s' % (model, field_name)})
                quick = target_model.name_create('Rapido %s %s' % (model, field_name))
            self.assertTrue(created)
            self.assertTrue(quick[0])

        bom_context = self._literal_context('mrp.bom', 'product_id')
        with self.assertLogs(
            'odoo.addons.kai_no_create_partner_product.models.kai_no_create',
            level='INFO',
        ) as logs:
            with self.assertRaises(UserError) as blocked_product:
                self.env['product.product'].with_user(self.blocked).with_context(bom_context).create({
                    'name': 'Producto bloqueado desde LdM',
                })
            with self.assertRaises(UserError):
                self.env['product.product'].with_user(self.blocked).with_context(bom_context).name_create(
                    'Rapido bloqueado desde LdM',
                )
        self.assertIn('crear productos', str(blocked_product.exception))
        self.assertTrue(any(
            'product.product' in message
            and self.blocked.login in message
            and str(bom_context[CONTEXT_KEY]) in message
            for message in logs.output
        ), logs.output)

        for model, field_name, target in cases:
            context = self._literal_context(model, field_name)
            target_model = self.env[target].with_user(self.blocked).with_context(context)
            with self.assertRaises(UserError) as blocked:
                if target == 'res.partner':
                    target_model.create({'name': 'Bloqueado %s' % model})
                else:
                    target_model.create({'name': 'Bloqueado %s' % field_name})
            if target == 'res.partner':
                self.assertIn('crear contactos', str(blocked.exception))
            else:
                self.assertIn('crear productos', str(blocked.exception))
            with self.assertRaises(UserError):
                target_model.name_create('Rapido bloqueado %s' % model)

        admin_partner = self.env['res.partner'].with_user(self.admin_user).with_context(
            **{CONTEXT_KEY: 'purchase.requisition.line'}
        ).create({'name': 'Contacto del administrador'})
        admin_product = self.env['product.product'].with_user(self.admin_user).with_context(
            **{CONTEXT_KEY: 'mrp.bom.line'}
        ).create({'name': 'Producto del administrador'})
        self.assertEqual(admin_partner.name, 'Contacto del administrador')
        self.assertTrue(admin_product.product_tmpl_id)

    def test_guarded_views_hide_create_for_users_outside_the_group(self):
        for model in GUARDED_MODELS:
            self.assertIn(model, self.env, model)
            for view_type in ('form', 'list'):
                arch = self._arch(model, view_type, self.blocked)
                if arch is None:
                    continue
                nodes = self._locked_field_nodes(arch)
                if view_type == 'form':
                    self.assertTrue(nodes, '%s form has no partner/product many2one' % model)
                for node in nodes:
                    self._assert_node_locked(node, '%s %s' % (model, view_type))
            allowed_arch = self._arch(model, 'form', self.allowed)
            if allowed_arch is not None:
                text = etree.tostring(allowed_arch, encoding='unicode')
                self.assertNotIn(CONTEXT_KEY, text, model)

    def test_every_purchase_order_line_product_view_is_locked(self):
        form = self._arch('purchase.order', 'form', self.blocked)
        nodes = form.xpath("//field[@name='product_id']")
        self.assertGreaterEqual(len(nodes), 3)
        for node in nodes:
            self._assert_node_locked(node, 'purchase.order form')

        views = self.env['ir.ui.view'].sudo().search([
            ('model', '=', 'purchase.order.line'),
            ('type', 'in', ('form', 'list', 'kanban')),
            ('mode', '=', 'primary'),
        ])
        self.assertTrue(views)
        seen = 0
        for view in views:
            arch = self._arch('purchase.order.line', view.type, self.blocked, view.id)
            self.assertIsNotNone(arch, view.name)
            for node in arch.xpath("//field[@name='product_id' or @name='partner_id']"):
                self._assert_node_locked(node, view.name)
                seen += 1
        self.assertGreaterEqual(seen, 1)

    def test_inventory_and_contacts_stay_open(self):
        for xmlid in (
            'product.product_template_action',
            'stock.product_template_action_product',
            'contacts.action_contacts',
        ):
            action = self.env.ref(xmlid)
            self.assertNotIn(CONTEXT_KEY, action.context or '', xmlid)
        open_models = [
            'product.template',
            'product.product',
            'product.supplierinfo',
            'res.partner',
            'res.users',
            'res.company',
            'res.config.settings',
            'ir.cron',
        ]
        # Odoo 19 moved packaging onto uom.uom. Keep the exclusion if the
        # historical model is still present.
        if 'product.packaging' in self.env:
            open_models.append('product.packaging')
        for model in open_models:
            arch, _view = self.env[model].with_user(self.blocked)._get_view(view_type='form')
            self.assertNotIn(
                CONTEXT_KEY,
                etree.tostring(arch, encoding='unicode'),
                model,
            )
        self.assertTrue(self.env['product.template'].with_user(self.blocked).create({
            'name': 'Desde inventario',
        }))
        self.assertTrue(self.env['product.product'].with_user(self.blocked).create({
            'name': 'Variante desde inventario',
        }))
        self.assertTrue(self.env['res.partner'].with_user(self.blocked).create({
            'name': 'Desde contactos',
        }))

    def test_pos_user_can_create_partner_the_way_pos_does(self):
        """The POS customer dialog is the res.partner form, not a many2one on pos.order.

        ``editPartner`` opens ``point_of_sale.res_partner_action_edit_pos`` and the
        web client creates the contact with that action context. The same user
        remains blocked when a guarded screen sends the marker context.
        """
        action = self.env.ref('point_of_sale.res_partner_action_edit_pos')
        self.assertEqual(action.res_model, 'res.partner')
        self.assertNotIn(CONTEXT_KEY, action.context or '')
        context = ast.literal_eval(action.context or '{}')
        self.assertNotIn(CONTEXT_KEY, context)

        arch = etree.fromstring(self.env['res.partner'].with_user(self.blocked).get_view(
            view_id=action.view_id.id,
            view_type='form',
        )['arch'])
        self.assertNotIn(CONTEXT_KEY, etree.tostring(arch, encoding='unicode'))

        partner = self.env['res.partner'].with_user(self.blocked).with_context(context).create({
            'name': 'Cliente creado desde el POS',
        })
        self.assertEqual(partner.name, 'Cliente creado desde el POS')
        quick_id, _quick_name = self.env['res.partner'].with_user(self.blocked).with_context(
            context,
        ).name_create('Cliente POS rapido')
        self.assertTrue(quick_id)

        with self.assertRaises(UserError):
            self.env['res.partner'].with_user(self.blocked).with_context(
                **{CONTEXT_KEY: 'purchase.order'}
            ).create({'name': 'No desde una compra'})

    def test_product_category_quick_create_is_unaffected(self):
        category_id, category_name = self.env['product.category'].with_user(self.blocked).with_context(
            **{CONTEXT_KEY: 'purchase.requisition.line'}
        ).name_create('Categoria libre Kai')
        self.assertTrue(category_id)
        self.assertEqual(category_name, 'Categoria libre Kai')

        arch = self._arch('product.pricelist.item', 'form', self.blocked)
        category_nodes = arch.xpath("//field[@name='categ_id']")
        self.assertTrue(category_nodes)
        for node in category_nodes:
            self.assertNotIn(CONTEXT_KEY, node.get('context') or '')
        self.assertTrue(self._locked_field_nodes(arch))
        for node in self._locked_field_nodes(arch):
            self._assert_node_locked(node, 'product.pricelist.item')

    def test_view_cache_key_differs_per_user(self):
        blocked_key = self.env['purchase.order'].with_user(self.blocked)._get_view_cache_key(
            view_type='form',
        )
        allowed_key = self.env['purchase.order'].with_user(self.allowed)._get_view_cache_key(
            view_type='form',
        )
        self.assertNotEqual(blocked_key, allowed_key)
        self.assertEqual(blocked_key[:-1], allowed_key[:-1])

        blocked_arch = self.env['purchase.order'].with_user(self.blocked).get_view(
            view_type='form',
        )['arch']
        allowed_arch = self.env['purchase.order'].with_user(self.allowed).get_view(
            view_type='form',
        )['arch']
        self.assertIn(CONTEXT_KEY, blocked_arch)
        self.assertNotIn(CONTEXT_KEY, allowed_arch)

        requisition_blocked = self.env['purchase.requisition'].with_user(
            self.blocked
        )._get_view_cache_key(view_type='form')
        requisition_allowed = self.env['purchase.requisition'].with_user(
            self.allowed
        )._get_view_cache_key(view_type='form')
        self.assertNotEqual(requisition_blocked, requisition_allowed)

    def test_option_and_context_literals_stay_python(self):
        sale_product_context = """{
            'default_lst_price': price_unit,
            'default_uom_id': product_uom_id,
            'partner_id': parent.partner_id,
        }"""
        invoice_partner_context = (
            "{'res_partner_search_mode': (context.get('default_move_type', 'entry') in "
            "('out_invoice', 'out_refund', 'out_receipt') and 'customer') or "
            "(context.get('default_move_type', 'entry') in "
            "('in_invoice', 'in_refund', 'in_receipt') and 'supplier') or False, "
            "'show_address': 1, 'default_is_company': True, 'show_vat': True}"
        )
        for original in ('', sale_product_context, invoice_partner_context, "{'default_is_company': True}"):
            injected = inject_context_key(original)
            ast.parse(injected, mode='eval')
            self.assertIn(CONTEXT_KEY, injected)
            self.assertEqual(ast.literal_eval(inject_context_key('{}'))[CONTEXT_KEY], True)

        self.assertEqual(inject_context_key('partner_id'), 'partner_id')
        traced = inject_context_key("{'default_is_storable': True}", 'mrp.bom.line')
        self.assertEqual(ast.literal_eval(traced)[CONTEXT_KEY], 'mrp.bom.line')
        self.assertEqual(inject_context_key(traced, 'stock.move'), traced)

        warning = "{\n    'show_label_warning': True\n}"
        merged = merge_no_create_options(warning)
        parsed = ast.literal_eval(merged)
        self.assertTrue(parsed['show_label_warning'])
        self.assertTrue(parsed['no_create'])
        self.assertTrue(parsed['no_create_edit'])
        self.assertTrue(parsed['no_quick_create'])

        quick = merge_no_create_options('{"no_quick_create": True}')
        parsed_quick = ast.literal_eval(quick)
        self.assertTrue(parsed_quick['no_quick_create'])
        self.assertTrue(parsed_quick['no_create'])
        self.assertEqual(quick.count('no_quick_create'), 1)

        already = merge_no_create_options(
            "{'no_create': True, 'no_create_edit': True, 'no_quick_create': True}"
        )
        self.assertEqual(
            already,
            "{'no_create': True, 'no_create_edit': True, 'no_quick_create': True}",
        )
        self.assertIsNone(merge_no_create_options('some_name'))

    def _arch(self, model, view_type, user, view_id=None):
        try:
            result = self.env[model].with_user(user).get_view(
                view_id=view_id,
                view_type=view_type,
            )
        except UserError:
            return None
        return etree.fromstring(result['arch'])

    def _locked_field_nodes(self, arch):
        names = ' or '.join("@name='%s'" % name for name in LOCKED_FIELD_NAMES)
        # ``data-used-by`` nodes are injected after the arch rewrite so a
        # domain or context can read the field. They are invisible and readonly.
        return [
            node for node in arch.xpath('//field[%s]' % names)
            if not node.get('data-used-by')
        ]

    def _assert_node_locked(self, node, label):
        options = ast.literal_eval(node.get('options') or '{}')
        self.assertTrue(options.get('no_create'), '%s %s' % (label, node.get('name')))
        self.assertTrue(options.get('no_create_edit'), '%s %s' % (label, node.get('name')))
        self.assertTrue(options.get('no_quick_create'), '%s %s' % (label, node.get('name')))
        context = node.get('context') or ''
        self.assertIn(CONTEXT_KEY, context, '%s %s' % (label, node.get('name')))
        ast.parse(context, mode='eval')
        ast.parse(node.get('options'), mode='eval')

    def _literal_context(self, model, field_name):
        arch = self._arch(model, 'form', self.blocked)
        self.assertIsNotNone(arch, model)
        for node in arch.xpath("//field[@name='%s']" % field_name):
            expr = node.get('context') or ''
            if CONTEXT_KEY not in expr:
                continue
            try:
                context = ast.literal_eval(expr)
            except (ValueError, SyntaxError):
                continue
            if isinstance(context, dict) and context.get(CONTEXT_KEY):
                return context
        self.fail('no literal guarded context on %s.%s' % (model, field_name))

    def _flag_column(self, user_id):
        self.env.cr.execute(
            """
            SELECT kai_allow_create_partner_product
              FROM res_users
             WHERE id = %s
            """,
            (user_id,),
        )
        return self.env.cr.fetchone()[0]

    def _migration_table_exists(self):
        self.env.cr.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM information_schema.tables
                 WHERE table_schema = 'public'
                   AND table_name = 'kai_nocreate_pp_allowed_user'
            )
            """
        )
        return self.env.cr.fetchone()[0]

    def _load_migration(self, version, filename, module_name):
        script = os.path.join(
            os.path.dirname(kai_no_create_partner_product.__file__),
            'migrations',
            version,
            filename,
        )
        spec = importlib.util.spec_from_file_location(module_name, script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.migrate
