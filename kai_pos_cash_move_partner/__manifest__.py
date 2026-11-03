{
    'name': 'POS: contacto en entrada y salida de efectivo',
    'summary': (
        'El cajero asigna contacto, facturas o diario destino al confirmar '
        'la entrada o salida de efectivo'
    ),
    'version': '19.0.1.2.1',
    'category': 'Sales/Point of Sale',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': [
        'point_of_sale',
        'oo_pos_cash_move_partner',
    ],
    'data': [
        'views/account_bank_statement_line_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'kai_pos_cash_move_partner/static/src/app/cash_move_popup/cash_move_popup.js',
            'kai_pos_cash_move_partner/static/src/app/cash_move_popup/cash_move_popup.xml',
            'kai_pos_cash_move_partner/static/src/app/cash_move_popup/cash_move_popup.scss',
        ],
        'web.assets_unit_tests': [
            'kai_pos_cash_move_partner/static/tests/**/*.test.js',
        ],
    },
    'installable': True,
    'application': False,
}
