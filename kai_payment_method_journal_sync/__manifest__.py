# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0.html).
{
    'name': 'Pagos: sincronizar método al cambiar el diario',
    'summary': (
        'Al cambiar el diario, reasigna el método de pago a la línea '
        'equivalente del diario nuevo'
    ),
    'description': (
        'Cuando el diario de un pago en borrador cambia, payment_method_line_id '
        'pasa a la línea del diario nuevo con el mismo método (mismo '
        'payment_method_id o el mismo código, por ejemplo own_checks). '
        'Si ese método no existe, usa la primera línea disponible. '
        'No crea diarios, líneas ni cuentas.'
    ),
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['account_payment_pro'],
    'installable': True,
    'application': False,
}
