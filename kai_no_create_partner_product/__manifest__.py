{
    'name': 'No crear contactos ni productos desde cotizaciones',
    'summary': (
        'Casilla en el usuario para impedir crear contactos y productos '
        'desde cotizaciones, facturas y recibos de compra y de venta'
    ),
    'version': '19.0.1.0.1',
    'category': 'Sales',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['sale', 'purchase', 'account'],
    'data': [
        'views/res_users_views.xml',
    ],
    'installable': True,
    'application': False,
}
