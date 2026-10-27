{
    'name': 'Bank Statements Menu (Extractos bancarios)',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'category': 'Accounting',
    'summary': 'Menú Contabilidad → Extractos bancarios (listado clásico de extractos)',
    'author': 'Juan Manuel',
    'depends': [
        'account_statement_base',
        'account_reconcile_oca',
    ],
    'data': [
        'views/account_bank_statement_menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
