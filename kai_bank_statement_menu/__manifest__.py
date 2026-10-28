{
    'name': 'Bank Statements Menu (Extractos bancarios)',
    'version': '19.0.1.2.0',
    'license': 'LGPL-3',
    'category': 'Accounting',
    'summary': 'Menú Contabilidad para extractos de banco, caja y tarjetas',
    'description': """
Menú Contabilidad para extractos de banco, caja y tarjetas.

En la conciliación de account_reconcile_oca, al abrir una línea de extracto
se selecciona la contrapartida pendiente (cuenta transitoria) para que
Operación manual traiga cuenta, contacto, etiqueta e importe sin un clic
extra en la línea gris.
""",
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
    'assets': {
        'web.assets_backend': [
            'kai_bank_statement_menu/static/src/components/account_reconcile_oca_data/auto_select_suspense_line.esm.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
