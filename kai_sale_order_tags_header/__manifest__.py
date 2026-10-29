{
    'name': 'Sale Order: tags in header',
    'summary': 'Show sale order tags (Etiquetas) in the form header and next to the number on the printed PDF, plus contact / secondary contact / delivery phones on the PDF',
    'version': '19.0.1.2.0',
    'category': 'Sales',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['sale'],
    'data': [
        'views/sale_order_views.xml',
        'report/sale_report_templates.xml',
    ],
    'installable': True,
    'application': False,
}
