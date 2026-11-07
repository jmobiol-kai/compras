{
    'name': 'Encabezados PDF de facturas argentinas',
    'summary': 'Repite la identificación del cliente en el PDF de facturas y notas de crédito argentinas, debajo del encabezado legal. Se instala solo si la localización argentina ya está instalada.',
    'version': '19.0.1.4.5',
    'category': 'Accounting/Localizations',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['kai_sale_order_tags_header', 'l10n_ar'],
    'data': [
        'report/l10n_ar_invoice_templates.xml',
    ],
    'installable': True,
    'auto_install': True,
    'application': False,
}
