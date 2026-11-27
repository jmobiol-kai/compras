# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import Command, fields
from odoo.tests import tagged
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestPaymentMethodJournalSync(AccountTestInvoicingCommon):
    """Cambio de diario en un pago de proveedor en borrador.

    Los dos diarios son de la misma compañía. Cada uno tiene Transferencia
    (manual) primero y Cheques propios (own_checks) después, con el mismo
    nombre en los dos. El módulo tiene que llevar el método a la línea del
    diario nuevo, no dejar la del diario anterior ni caer a Transferencia
    si Cheques propios existe.
    """

    @classmethod
    def get_default_groups(cls):
        """El usuario de test tiene que poder reactivar la docena.

        ``AccountTestInvoicingCommon`` termina en ``UomCommon.setUpClass``,
        que hace ``uom_dozen.active = True`` (uom/tests/common.py). En una
        base real ese usuario no trae ``uom.group_uom`` (Gestión de Unidades
        de Medida) y el write tira AccessError. ``BaseCommon`` arma el
        usuario con estos grupos antes de ese write, así que el grupo tiene
        que estar acá: ``cls.env`` todavía no existe al entrar a nuestro
        ``setUpClass``, y el usuario que escribe la unidad se crea adentro
        del ``super()``.
        """
        groups = super().get_default_groups()
        group_uom = cls.env.ref('uom.group_uom', raise_if_not_found=False)
        if group_uom:
            groups |= group_uom
        return groups

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data['company']
        cls.proveedor = cls.env['res.partner'].create({
            'name': 'Proveedor Fisa',
            'supplier_rank': 1,
        })
        payable = cls.company_data['default_account_payable']
        cls.proveedor.with_company(cls.company).property_account_payable_id = payable

        cls.cuenta_cheques = cls._cuenta_cheques_pendientes()
        # Sin cuenta de liquidez: el alta del diario crea la suya. Compartir
        # la del diario de prueba puede chocar con la unicidad del banco.
        cls.diario_a = cls._diario_banco('Banco Mercado Pago', 'KMPG')
        cls.diario_b = cls._diario_banco('Banco Santander', 'KSAN')
        cls.transferencia_a = cls._linea_metodo(
            cls.diario_a, 'manual', 'Transferencia', 1,
        )
        cls.cheques_a = cls._linea_metodo(
            cls.diario_a, 'own_checks', 'Cheques propios', 20, cls.cuenta_cheques,
        )
        cls.transferencia_b = cls._linea_metodo(
            cls.diario_b, 'manual', 'Transferencia', 1,
        )
        cls.cheques_b = cls._linea_metodo(
            cls.diario_b, 'own_checks', 'Cheques propios', 20, cls.cuenta_cheques,
        )
        primera_b = cls.diario_b._get_available_payment_method_lines('outbound')[:1]
        if primera_b != cls.transferencia_b:
            raise AssertionError(
                'Santander tiene que ofrecer Transferencia antes que Cheques propios '
                'para poder distinguir el mapeo de «la primera línea».'
            )

    @classmethod
    def _cuenta_cheques_pendientes(cls):
        company = cls.company_data['company']
        account = cls.env['account.account'].search([
            ('account_type', '=', 'asset_current'),
            ('reconcile', '=', True),
            ('company_ids', 'in', company.ids),
        ], limit=1)
        if account:
            return account
        return cls.env['account.account'].create({
            'name': 'Cheques pendientes',
            'code': '199901',
            'account_type': 'asset_current',
            'reconcile': True,
            'company_ids': [Command.link(company.id)],
        })

    @classmethod
    def _diario_banco(cls, name, code):
        return cls.env['account.journal'].create({
            'name': name,
            'code': code,
            'type': 'bank',
            'company_id': cls.company_data['company'].id,
        })

    @classmethod
    def _linea_metodo(cls, journal, code, name, sequence, outstanding=None):
        line = journal.outbound_payment_method_line_ids.filtered(
            lambda item: item.code == code
        )[:1]
        if not line:
            method = cls.env['account.payment.method'].search([
                ('code', '=', code),
                ('payment_type', '=', 'outbound'),
            ], limit=1)
            if not method:
                xmlid = {
                    'manual': 'account.account_payment_method_manual_out',
                    'own_checks': 'l10n_latam_check.account_payment_method_own_checks',
                }[code]
                method = cls.env.ref(xmlid)
            line = cls.env['account.payment.method.line'].create({
                'name': name,
                'payment_method_id': method.id,
                'journal_id': journal.id,
                'sequence': sequence,
            })
        line.write({'name': name, 'sequence': sequence})
        if outstanding and not line.payment_account_id:
            line.payment_account_id = outstanding
        return line

    def _pago_proveedor(self, journal, method_line, amount=100.0, partner=None):
        return self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': (partner or self.proveedor).id,
            'amount': amount,
            'journal_id': journal.id,
            'payment_method_line_id': method_line.id,
            'company_id': self.company.id,
        })

    def _cheque(self, payment, number, amount):
        return self.env['l10n_latam.check'].create({
            'payment_id': payment.id,
            'name': number,
            'payment_date': fields.Date.context_today(payment),
            'amount': amount,
        })

    def test_cambiar_diario_conserva_cheques_propios(self):
        pago = self._pago_proveedor(self.diario_a, self.cheques_a)
        company = pago.company_id
        diarios = self.env['account.journal'].search_count([])
        lineas = self.env['account.payment.method.line'].search_count([])

        pago.write({'journal_id': self.diario_b.id})

        self.assertEqual(pago.journal_id, self.diario_b)
        self.assertEqual(pago.payment_method_line_id, self.cheques_b)
        self.assertNotEqual(pago.payment_method_line_id, self.cheques_a)
        self.assertNotEqual(pago.payment_method_line_id, self.transferencia_b)
        self.assertEqual(pago.payment_method_line_id.code, 'own_checks')
        self.assertEqual(pago.company_id, company)
        self.assertEqual(self.env['account.journal'].search_count([]), diarios)
        self.assertEqual(self.env['account.payment.method.line'].search_count([]), lineas)

    def test_write_conjunto_como_el_pago_2440_y_confirmar(self):
        # Diario Mercado Pago con Transferencia. El formulario manda el
        # diario Santander y «Cheques propios» del diario anterior (mismo
        # nombre). No tiene que saltar el constraint, y al confirmar el
        # método tiene que ser el own_checks de Santander.
        pago = self._pago_proveedor(self.diario_a, self.transferencia_a, amount=2440.0)
        pago.write({
            'journal_id': self.diario_b.id,
            'payment_method_line_id': self.cheques_a.id,
        })
        self.assertEqual(pago.payment_method_line_id, self.cheques_b)
        self.assertEqual(pago.payment_method_line_id.journal_id, pago.journal_id)

        self._cheque(pago, '00002440', 2440.0)
        pago.action_post()
        self.assertIn(pago.state, ('in_process', 'paid'))
        self.assertEqual(pago.payment_method_line_id, self.cheques_b)
        self.assertTrue(pago.l10n_latam_new_check_ids)

    def test_sin_own_checks_en_el_diario_nuevo_usa_la_primera(self):
        self.cheques_b.unlink()
        pago = self._pago_proveedor(self.diario_a, self.cheques_a)
        pago.write({'journal_id': self.diario_b.id})
        primera = self.diario_b._get_available_payment_method_lines('outbound')[:1]
        self.assertEqual(pago.payment_method_line_id, primera)
        self.assertEqual(pago.payment_method_line_id.journal_id, self.diario_b)
        self.assertNotEqual(pago.payment_method_line_id.code, 'own_checks')
        self.assertEqual(primera, self.transferencia_b)

    def test_los_cheques_siguen_al_pasar_a_un_diario_con_own_checks(self):
        pago = self._pago_proveedor(self.diario_a, self.cheques_a, amount=150.0)
        cheque = self._cheque(pago, '00000150', 150.0)
        pago.write({'journal_id': self.diario_b.id})
        self.assertEqual(pago.payment_method_line_id, self.cheques_b)
        self.assertEqual(pago.l10n_latam_new_check_ids, cheque)

        pago.action_post()
        self.assertIn(pago.state, ('in_process', 'paid'))
        self.assertEqual(pago.l10n_latam_new_check_ids, cheque)
        self.assertEqual(pago.payment_method_code, 'own_checks')

    def test_el_default_del_partner_no_pisa_cheques_al_cambiar_diario(self):
        self.proveedor.with_company(self.company).property_outbound_payment_method_line_id = (
            self.transferencia_b
        )
        pago = self._pago_proveedor(self.diario_a, self.cheques_a)
        pago.write({'journal_id': self.diario_b.id})
        self.assertEqual(pago.payment_method_line_id, self.cheques_b)

    def test_pago_nuevo_sin_metodo_usa_el_default_del_partner(self):
        self.proveedor.with_company(self.company).property_outbound_payment_method_line_id = (
            self.transferencia_b
        )
        pago = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.proveedor.id,
            'amount': 25.0,
            'journal_id': self.diario_b.id,
            'company_id': self.company.id,
        })
        self.assertEqual(pago.payment_method_line_id, self.transferencia_b)

    def test_create_con_metodo_de_otro_diario(self):
        pago = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.proveedor.id,
            'amount': 40.0,
            'journal_id': self.diario_b.id,
            'payment_method_line_id': self.cheques_a.id,
            'company_id': self.company.id,
        })
        self.assertEqual(pago.payment_method_line_id, self.cheques_b)
        self.assertEqual(pago.state, 'draft')

    def test_write_de_varios_pagos_asigna_la_linea_de_cada_diario(self):
        pago_a = self._pago_proveedor(self.diario_a, self.transferencia_a, amount=10.0)
        pago_b = self._pago_proveedor(self.diario_b, self.transferencia_b, amount=20.0)
        (pago_a | pago_b).write({
            'payment_method_line_id': self.cheques_a.id,
        })
        self.assertEqual(pago_a.payment_method_line_id, self.cheques_a)
        self.assertEqual(pago_b.payment_method_line_id, self.cheques_b)
        self.assertEqual(pago_a.journal_id, self.diario_a)
        self.assertEqual(pago_b.journal_id, self.diario_b)

    def test_al_cambiar_el_diario_en_memoria_se_mapea_el_metodo(self):
        # new() dispara el cómputo como el onchange, sin guardar.
        pago = self.env['account.payment'].new({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.proveedor.id,
            'amount': 80.0,
            'journal_id': self.diario_a.id,
            'payment_method_line_id': self.cheques_a.id,
            'company_id': self.company.id,
        })
        self.assertEqual(pago.payment_method_line_id, self.cheques_a)
        pago.journal_id = self.diario_b
        self.assertEqual(pago.payment_method_line_id, self.cheques_b)
        self.assertEqual(pago.payment_method_line_id.journal_id, self.diario_b)
