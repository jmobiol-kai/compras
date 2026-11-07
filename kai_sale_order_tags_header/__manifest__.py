{
    'name': 'Sale Order: tags in header',
    'summary': 'Show sale order tags (Etiquetas) in the form header and next to the number on the printed PDF, plus contact / secondary contact / delivery phones on the PDF. Show the delivery date (commitment_date) next to the order date, and print that date and time on the quotation, order and proforma PDF. Repeat a compact customer / order / dates / tags header on every PDF page, with a sale-only paper format so the block sits under the logo.',
    'version': '19.0.1.4.2',
    'category': 'Sales',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['sale'],
    'data': [
        'report/paperformat.xml',
        'views/sale_order_views.xml',
        'report/sale_report_templates.xml',
    ],
    'installable': True,
    'application': False,
}
