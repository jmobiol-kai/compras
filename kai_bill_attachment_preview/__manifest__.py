{
    'name': 'Vista previa del PDF en facturas publicadas',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'category': 'Accounting',
    'summary': 'Muestra el PDF adjunto en facturas y facturas de proveedor también después de publicarlas',
    'description': """
Vista previa del PDF en facturas de cliente y de proveedor.

En Odoo 19 Community, account.view_move_form deja el panel
o_attachment_preview solo mientras el comprobante está en borrador
(state != 'draft'). Al publicarlo, el formulario queda con el chatter
a la derecha. Este módulo relaja esa condición: la vista previa se
muestra en facturas, notas de crédito, facturas de proveedor y
reembolsos, en borrador y publicados.

No toca el chatter. En pantallas XXL, si hay un adjunto visible, el
layout COMBO de mail deja el PDF al costado y el chatter debajo.
""",
    'author': 'Juan Manuel',
    'depends': ['account'],
    'data': [
        'views/account_move_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
