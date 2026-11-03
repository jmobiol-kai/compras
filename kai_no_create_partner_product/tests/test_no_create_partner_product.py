# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

import ast
import importlib.util
import os

from lxml import etree

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

import odoo.addons.kai_no_create_partner_product as kai_no_create_partner_product
from odoo.addons.kai_no_create_partner_product.models.kai_no_create import (
    CONTEXT_KEY,
    inject_context_key,
    merge_no_create_options,
)


@tagged('post_install', '-at_install')
class TestKaiNoCreatePartnerProduct(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env['res.partner']
        cls.product_model = cls.env['product.product']
        cls.template_model = cls.env['product.template']

    def test_flag_defaults_to_blocked(self):
        self.assertFalse(self.env.user.kai_allow_create_partner_product)
        user = self.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Usuario Kai sin preferencia',
            'login': 'kai_no_create_default',
            'email': 'kai_no_create_default@example.com',
        })
        self.assertFalse(user.kai_allow_create_partner_product)
        with self.assertRaises(AccessError):
            user.with_user(user).write({'kai_allow_create_partner_product': True})
        self.assertFalse(user.kai_allow_create_partner_product)

        admin = self.env.ref('base.user_admin')
        admin.with_user(admin).write({'kai_allow_create_partner_product': True})
        self.assertTrue(admin.kai_allow_create_partner_product)
        admin.with_user(admin).write({'kai_allow_create_partner_product': False})
        self.assertFalse(admin.kai_allow_create_partner_product)

    def test_upgrade_migration_clears_existing_users(self):
        Users = self.env['res.users'].with_context(
            no_reset_password=True,
            mail_create_nosubscribe=True,
        )
        allowed = Users.create({
            'name': 'Usuario Kai antes permitido',
            'login': 'kai_no_create_upgrade',
            'email': 'kai_no_create_upgrade@example.com',
            'kai_allow_create_partner_product': True,
        })
        self.assertTrue(allowed.kai_allow_create_partner_product)
        self.env.flush_all()

        migrate = self._load_upgrade_migration()
        migrate(self.env.cr, None)
        allowed.invalidate_recordset()
        self.assertTrue(allowed.kai_allow_create_partner_product)

        migrate(self.env.cr, '19.0.1.0.1')
        allowed.invalidate_recordset()
        self.env.user.invalidate_recordset()
        self.assertFalse(allowed.kai_allow_create_partner_product)
        self.assertFalse(self.env.user.kai_allow_create_partner_product)

        created_after = Users.create({
            'name': 'Usuario Kai despues de actualizar',
            'login': 'kai_no_create_after_upgrade',
            'email': 'kai_no_create_after_upgrade@example.com',
        })
        self.assertFalse(created_after.kai_allow_create_partner_product)

    def _load_upgrade_migration(self):
        script = os.path.join(
            os.path.dirname(kai_no_create_partner_product.__file__),
            'migrations',
            '19.0.1.0.2',
            'post-migrate.py',
        )
        spec = importlib.util.spec_from_file_location(
            'kai_no_create_partner_product_post_migrate_19_0_1_0_2',
            script,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.migrate

    def test_create_from_commercial_context_follows_the_flag(self):
        sources = ('sale.order', 'purchase.order', 'account.move', 'account.payment')

        self.env.user.kai_allow_create_partner_product = True
        for source in sources:
            partner = self.partner_model.with_context(**{CONTEXT_KEY: source}).create({
                'name': 'Contacto permitido %s' % source,
            })
            self.assertEqual(partner.name, 'Contacto permitido %s' % source)
        product = self.product_model.with_context(**{CONTEXT_KEY: 'sale.order'}).create({
            'name': 'Producto permitido',
        })
        template = self.template_model.with_context(**{CONTEXT_KEY: 'purchase.order'}).create({
            'name': 'Plantilla permitida',
        })
        self.assertTrue(product.product_tmpl_id)
        self.assertEqual(template.name, 'Plantilla permitida')
        quick = self.partner_model.with_context(**{CONTEXT_KEY: 'account.payment'}).name_create(
            'Contacto rápido permitido',
        )
        self.assertTrue(quick[0])

        self.env.user.kai_allow_create_partner_product = False
        for source in sources:
            with self.assertRaises(UserError) as blocked:
                self.partner_model.with_context(**{CONTEXT_KEY: source}).create({
                    'name': 'Contacto bloqueado %s' % source,
                })
            self.assertIn('crear contactos', str(blocked.exception))
            with self.assertRaises(UserError):
                self.partner_model.with_context(**{CONTEXT_KEY: source}).name_create(
                    'Rápido bloqueado %s' % source,
                )
        with self.assertRaises(UserError) as blocked_product:
            self.product_model.with_context(**{CONTEXT_KEY: 'account.move'}).create({
                'name': 'Producto bloqueado',
            })
        self.assertIn('crear productos', str(blocked_product.exception))
        with self.assertRaises(UserError):
            self.template_model.with_context(**{CONTEXT_KEY: 'sale.order'}).name_create(
                'Plantilla bloqueada',
            )
        with self.assertRaises(UserError):
            self.product_model.with_context(**{CONTEXT_KEY: 'purchase.order'}).name_create(
                'Variante bloqueada',
            )

        # Contactos and Productos stay open: the block is only the document context.
        self.assertTrue(self.partner_model.create({'name': 'Desde contactos'}))
        self.assertTrue(self.product_model.create({'name': 'Desde productos'}))

    def test_forms_hide_create_only_when_the_flag_is_off(self):
        self.env.user.kai_allow_create_partner_product = True
        for model, xpath in self._guarded_fields():
            arch = self._form_arch(model)
            for node in arch.xpath(xpath):
                self.assertNotIn(CONTEXT_KEY, node.get('context') or '')
                options = node.get('options')
                if options:
                    self.assertFalse(ast.literal_eval(options).get('no_create'))

        self.env.user.kai_allow_create_partner_product = False
        for model, xpath in self._guarded_fields():
            arch = self._form_arch(model)
            nodes = arch.xpath(xpath)
            self.assertTrue(nodes, '%s missing %s' % (model, xpath))
            for node in nodes:
                options = ast.literal_eval(node.get('options') or '{}')
                self.assertTrue(options.get('no_create'), '%s %s' % (model, node.get('name')))
                self.assertTrue(options.get('no_create_edit'), '%s %s' % (model, node.get('name')))
                self.assertTrue(options.get('no_quick_create'), '%s %s' % (model, node.get('name')))
                context = node.get('context') or ''
                self.assertIn(CONTEXT_KEY, context)
                ast.parse(context, mode='eval')
                ast.parse(node.get('options'), mode='eval')

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

    def _form_arch(self, model):
        return etree.fromstring(self.env[model].get_view(view_type='form')['arch'])

    def _guarded_fields(self):
        return (
            ('sale.order', "//field[@name='partner_id'][@widget='res_partner_many2one']"),
            ('sale.order', "//field[@name='partner_invoice_id']"),
            ('sale.order', "//field[@name='partner_shipping_id']"),
            ('sale.order', "//field[@name='product_template_id'][@widget='sol_product_many2one']"),
            ('sale.order', "//field[@name='product_id'][@widget='sol_product_many2one']"),
            ('sale.order', "//field[@name='product_id'][@widget='many2one_barcode']"),
            ('purchase.order', "//field[@name='partner_id'][@widget='res_partner_many2one']"),
            ('purchase.order', "//field[@name='product_id'][@widget='many2one_barcode']"),
            (
                'purchase.order',
                "//field[@name='product_id'][@widget='product_label_section_and_note_field']",
            ),
            ('account.move', "//field[@name='partner_id'][@widget='res_partner_many2one']"),
            ('account.move', "//field[@name='partner_shipping_id']"),
            (
                'account.move',
                "//field[@name='product_id'][@widget='product_label_section_and_note_field']",
            ),
            ('account.payment', "//sheet//field[@name='partner_id']"),
        )
