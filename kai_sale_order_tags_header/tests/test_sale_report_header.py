from lxml import html

from odoo.tests import TransactionCase, tagged


def _text(node):
    return ' '.join(node.text_content().split())


@tagged('post_install', '-at_install')
class TestSaleReportHeader(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'Producto ficticio',
            'list_price': 10.0,
            'type': 'consu',
        })
        cls.tag_short = cls.env['crm.tag'].create({
            'name': 'Retira demo',
            'color': 2,
        })
        cls.tag_long = cls.env['crm.tag'].create({
            'name': 'Catering evento corporativo de varios dias',
            'color': 4,
        })
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente Ficticio Alfa',
            'street': 'Calle Falsa 123',
            'street2': 'Piso 4',
            'city': 'Ciudad Demo',
            'zip': '1000',
            'phone': '555-0100',
        })
        cls.order = cls._create_order(cls.partner, [cls.tag_short], qty_lines=1)

    @classmethod
    def _create_order(cls, partner, tags, qty_lines):
        order = cls.env['sale.order'].create({
            'partner_id': partner.id,
            'tag_ids': [(6, 0, [tag.id for tag in tags])],
            'commitment_date': '2026-04-07 22:00:00',
        })
        cls.env['sale.order.line'].create([
            {
                'order_id': order.id,
                'product_id': cls.product.id,
                'product_uom_qty': 1,
                'price_unit': 10,
                'name': 'Producto ficticio %02d' % (index + 1),
            }
            for index in range(qty_lines)
        ])
        return order

    def _html(self, orders):
        content, report_type = self.env['ir.actions.report']._render_qweb_html(
            'sale.report_saleorder', orders.ids,
        )
        self.assertEqual(report_type, 'html')
        if isinstance(content, bytes):
            content = content.decode()
        return html.fromstring(content)

    def test_sale_paperformat_leaves_the_company_format_alone(self):
        euro = self.env.ref('base.paperformat_euro')
        sale_format = self.env.ref('kai_sale_order_tags_header.paperformat_saleorder')
        self.assertNotEqual(euro, sale_format)
        self.assertFalse(sale_format.default)
        self.assertEqual(sale_format.margin_top, 80)
        self.assertEqual(sale_format.header_spacing, 72)
        self.assertEqual(sale_format.margin_bottom, 32)
        self.assertTrue(sale_format.css_margins)

        sale_report = self.env.ref('sale.action_report_saleorder')
        proforma = self.env.ref('sale.action_report_pro_forma_invoice')
        self.assertEqual(sale_report.get_paperformat(), sale_format)
        self.assertEqual(proforma.get_paperformat(), sale_format)

        invoice = self.env.ref('account.account_invoices')
        self.assertNotEqual(invoice.get_paperformat(), sale_format)
        self.assertEqual(invoice.get_paperformat(), euro)

        raw = self.env['ir.actions.report'].search(
            [('report_name', '=', 'sale.report_saleorder_raw')], limit=1,
        )
        if raw:
            self.assertEqual(raw.get_paperformat(), sale_format)

    def test_customer_block_is_in_the_header_once(self):
        root = self._html(self.order)
        header = root.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]"
        )[0]
        article = root.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' article ')]"
        )[0]
        header_text = _text(header)
        self.assertIn('Cliente Ficticio Alfa', header_text)
        self.assertIn('Calle Falsa 123', header_text)
        self.assertIn('555-0100', header_text)
        self.assertIn(self.order.name, header_text)
        self.assertIn('Retira demo', header_text)
        self.assertIn('19:00', header_text)
        self.assertIn(self.order.name, _text(header.xpath(".//*[@name='kai_sale_repeat']")[0]))
        self.assertTrue(header.xpath(".//*[@id='informations']"))
        self.assertFalse(article.xpath(".//*[@id='informations']"))
        self.assertFalse(article.xpath(".//h2"))
        self.assertNotIn('Calle Falsa 123', _text(article))
        self.assertIn('Producto ficticio', _text(article))

    def test_batch_headers_do_not_mix_customers(self):
        other_partner = self.env['res.partner'].create({
            'name': 'Cliente Ficticio Beta',
            'street': 'Avenida Inventada 456',
            'city': 'Otra Ciudad',
            'phone': '555-0199',
        })
        other = self._create_order(other_partner, [self.tag_long], qty_lines=1)
        root = self._html(self.order | other)
        headers = root.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]"
        )
        self.assertEqual(len(headers), 2)
        texts = [_text(node) for node in headers]
        self.assertTrue(any('Cliente Ficticio Alfa' in text and 'Cliente Ficticio Beta' not in text for text in texts))
        self.assertTrue(any('Cliente Ficticio Beta' in text and 'Cliente Ficticio Alfa' not in text for text in texts))
        self.assertTrue(any('555-0100' in text and '555-0199' not in text for text in texts))
        self.assertTrue(any('555-0199' in text and '555-0100' not in text for text in texts))

    def test_long_order_keeps_a_single_header_block(self):
        # wkhtmltopdf is not called here: during a test the renderer and the
        # asset HTTP request deadlock on the same transaction. The PDF check
        # is the fictional render run outside the test cursor.
        long_partner = self.env['res.partner'].create({
            'name': 'Cliente Ficticio Largo',
            'street': 'Avenida Inventada 4567 Piso 12',
            'street2': 'Torre Demo Oficina 8',
            'city': 'Ciudad Grande',
            'zip': '1000',
            'phone': '555-0101',
        })
        self.env['res.partner'].create({
            'name': 'Contacto Demo',
            'parent_id': long_partner.id,
            'type': 'contact',
            'phone': '555-0102',
        })
        shipping = self.env['res.partner'].create({
            'name': 'Deposito Ficticio Norte',
            'parent_id': long_partner.id,
            'type': 'delivery',
            'street': 'Ruta Inventada km 12',
            'city': 'Ciudad Norte',
            'phone': '555-0103',
        })
        order = self._create_order(
            long_partner, [self.tag_short, self.tag_long], qty_lines=40,
        )
        order.partner_shipping_id = shipping
        root = self._html(order)
        headers = root.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]"
        )
        self.assertEqual(len(headers), 1)
        header_text = _text(headers[0])
        self.assertIn('Cliente Ficticio Largo', header_text)
        self.assertIn('555-0101', header_text)
        self.assertIn('555-0102', header_text)
        self.assertIn('555-0103', header_text)
        self.assertIn('Deposito Ficticio Norte', header_text)
        self.assertIn('Catering evento corporativo de varios dias', header_text)
        self.assertIn(order.name, header_text)
        article = root.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' article ')]"
        )[0]
        self.assertNotIn('Avenida Inventada 4567', _text(article))
        self.assertNotIn('Deposito Ficticio Norte', _text(article))
        self.assertEqual(_text(article).count('Producto ficticio'), 40)
