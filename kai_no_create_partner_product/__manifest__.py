{
    'name': 'No crear contactos ni productos fuera de Inventario y Contactos',
    'summary': (
        'Impide crear contactos y productos desde otras pantallas. '
        'Sigue permitido en Inventario, en Contactos y para quien tenga el permiso.'
    ),
    'version': '19.0.1.1.0',
    'category': 'Technical',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['sale', 'purchase', 'account'],
    'data': [
        'security/kai_security.xml',
    ],
    'installable': True,
    'application': False,
}
