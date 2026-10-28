{
    'name': 'Bank Statements Menu (Extractos bancarios)',
    'version': '19.0.1.1.0',
    'license': 'LGPL-3',
    'category': 'Accounting',
    'summary': 'Menú Contabilidad para extractos de banco, caja y tarjetas',
    'author': 'Juan Manuel',
    'depends': [
        'account_statement_base',
        'account_reconcile_oca',
        'account_statement_import_file',
        'account_statement_import_sheet_file',
    ],
    'data': [
        'views/account_bank_statement_menu.xml',
        'views/account_journal_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
