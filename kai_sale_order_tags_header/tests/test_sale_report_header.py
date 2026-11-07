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

    def test_each_header_measures_its_own_margin(self):
        report = self.env.ref('sale.action_report_saleorder')
        paperformat = report.get_paperformat()
        short = (
            '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
            '<body style="margin:0"><div class="header" style="font-family:sans-serif">'
            '<div style="height:12mm;width:30mm;background:#222"></div>'
            '<div>Cliente Ficticio Alfa</div>'
            '<div name="kai_sale_repeat" style="border-bottom:0.4mm solid #222">07/04/2026 19:00</div>'
            '</div></body></html>'
        )
        tall = short.replace(
            '<div>Cliente Ficticio Alfa</div>',
            '<div>Cliente Ficticio Largo</div>' + '<div>Linea de direccion ficticia</div>' * 12,
            1,
        )
        short_args = report._kai_measured_paper_args(short, paperformat)
        tall_args = report._kai_measured_paper_args(tall, paperformat)
        self.assertTrue(short_args and tall_args)
        short_top = float(short_args['data-report-margin-top'])
        tall_top = float(tall_args['data-report-margin-top'])
        self.assertLess(short_top, 70)
        self.assertGreater(tall_top, short_top + 8)
        self.assertAlmostEqual(float(short_args['data-report-header-spacing']), short_top - 8, delta=0.05)
        doubled = short.replace(
            '</body>',
            '<div class="header"><div name="kai_sale_repeat">Copia</div></div></body>',
        )
        self.assertFalse(report._kai_measured_paper_args(doubled, paperformat))
        self.assertFalse(report._kai_measured_paper_args(short.replace(' name="kai_sale_repeat"', ''), paperformat))
        invoice = self.env.ref('account.account_invoices')
        invoice_args = invoice._build_wkhtmltopdf_args(invoice.get_paperformat(), False)
        self.assertIn('--margin-top', invoice_args)
        self.assertEqual(invoice_args[invoice_args.index('--margin-top') + 1], str(invoice.get_paperformat().margin_top))

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

    def _html_report(self, report_name, records):
        content, report_type = self.env['ir.actions.report']._render_qweb_html(
            report_name, records.ids,
        )
        self.assertEqual(report_type, 'html')
        if isinstance(content, bytes):
            content = content.decode()
        return html.fromstring(content)

    def test_purchase_and_customer_invoice_repeat_vendor_bill_does_not(self):
        sale_format = self.env.ref('kai_sale_order_tags_header.paperformat_saleorder')
        self.assertEqual(
            self.env.ref('purchase.action_report_purchase_order').get_paperformat(),
            sale_format,
        )
        self.assertEqual(
            self.env.ref('purchase.report_purchase_quotation').get_paperformat(),
            sale_format,
        )
        self.assertNotEqual(
            self.env.ref('account.account_invoices').get_paperformat(),
            sale_format,
        )
        self.assertNotEqual(
            self.env.ref('account.action_account_original_vendor_bill').get_paperformat(),
            sale_format,
        )
        vendor = self.env['res.partner'].create({
            'name': 'Proveedor Ficticio Norte',
            'street': 'Calle Proveedor 50',
            'city': 'Ciudad Demo',
            'phone': '555-0170',
            'supplier_rank': 1,
        })
        product = self.product
        product.purchase_ok = True
        order = self.env['purchase.order'].create({
            'partner_id': vendor.id,
            'partner_ref': 'REF-FICT-1',
            'order_line': [(0, 0, {
                'product_id': product.id,
                'name': 'Producto ficticio compra',
                'product_qty': 2,
                'price_unit': 15,
                'date_planned': '2026-04-20',
            })],
        })
        rfq = self._html_report('purchase.report_purchasequotation', order)
        header = rfq.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]")[0]
        self.assertIn('Proveedor Ficticio Norte', _text(header))
        self.assertIn(order.name, _text(header))
        order.button_confirm()
        po = self._html_report('purchase.report_purchaseorder', order)
        po_header = po.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]")[0]
        po_article = po.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' article ')]")[0]
        self.assertIn('Proveedor Ficticio Norte', _text(po_header))
        self.assertIn('REF-FICT-1', _text(po_header))
        self.assertIn(order.name, _text(po_header))
        self.assertFalse(po_article.xpath(".//*[@id='informations']"))
        self.assertIn('Producto ficticio compra', _text(po_article))

        out_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': '2026-04-07',
            'invoice_line_ids': [(0, 0, {
                'name': 'Producto ficticio factura',
                'quantity': 1,
                'price_unit': 20,
            })],
        })
        customer = self._html_report('account.report_invoice_with_payments', out_invoice)
        customer_header = customer.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]"
        )[0]
        customer_article = customer.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' article ')]"
        )[0]
        self.assertIn('Cliente Ficticio Alfa', _text(customer_header))
        self.assertIn('Calle Falsa 123', _text(customer_header))
        self.assertTrue(customer_header.xpath(".//*[@name='kai_sale_repeat']"))
        self.assertNotIn('Calle Falsa 123', _text(customer_article))
        self.assertIn('Producto ficticio factura', _text(customer_article))

        credit = self.env['account.move'].create({
            'move_type': 'out_refund',
            'partner_id': self.partner.id,
            'invoice_date': '2026-04-09',
            'invoice_line_ids': [(0, 0, {
                'name': 'Nota de credito ficticia',
                'quantity': 1,
                'price_unit': 5,
            })],
        })
        credit_html = self._html_report('account.report_invoice', credit)
        credit_header = credit_html.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]"
        )[0]
        self.assertTrue(credit_header.xpath(".//*[@name='kai_sale_repeat']"))
        self.assertIn('Cliente Ficticio Alfa', _text(credit_header))

        in_invoice = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': vendor.id,
            'invoice_date': '2026-04-08',
            'invoice_line_ids': [(0, 0, {
                'name': 'Gasto ficticio proveedor',
                'quantity': 1,
                'price_unit': 30,
            })],
        })
        vendor_bill = self._html_report('account.report_invoice_with_payments', in_invoice)
        bill_header = vendor_bill.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]"
        )[0]
        bill_article = vendor_bill.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' article ')]"
        )[0]
        self.assertFalse(bill_header.xpath(".//*[@name='kai_sale_repeat']"))
        self.assertIn('Proveedor Ficticio Norte', _text(bill_article))
        self.assertIn('Gasto ficticio proveedor', _text(bill_article))

        if self.env.ref('l10n_ar.report_invoice_document', raise_if_not_found=False):
            ar_view = self.env.ref('kai_sale_order_tags_header.l10n_ar_report_invoice_repeat_header')
            self.assertEqual(ar_view.inherit_id, self.env.ref('l10n_ar.report_invoice_document'))
            self.assertNotIn('qrcode', ar_view.arch)
            self.assertIn('is_sale_document', ar_view.arch)
