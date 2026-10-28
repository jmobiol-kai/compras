{
    'name': 'Vista previa del PDF en facturas publicadas',
    'version': '19.0.1.1.0',
    'license': 'LGPL-3',
    'category': 'Accounting',
    'summary': 'Muestra el PDF adjunto al costado en facturas y facturas de proveedor, también publicadas',
    'description': """
Vista previa del PDF en facturas de cliente y de proveedor.

En Odoo 19 Community, account.view_move_form deja el panel
o_attachment_preview solo mientras el comprobante está en borrador
(state != 'draft'). Este módulo relaja esa condición: la vista previa se
muestra en facturas, notas de crédito, facturas de proveedor y
reembolsos, en borrador y publicados.

Además, OCA web_responsive anula FormRenderer.hasFile() (siempre false),
con lo que mail nunca usa el layout COMBO y el chatter tapa el panel. Un
parche JS sobre mailLayout() recupera COMBO solo para account.move: en
pantallas XXL con un PDF o imagen adjunto, el PDF queda al costado del
formulario y el chatter debajo, como en Enterprise.
""",
    'author': 'Juan Manuel',
    'depends': ['account'],
    'data': [
        'views/account_move_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'kai_bill_attachment_preview/static/src/views/form_renderer.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
