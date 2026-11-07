{
    'name': 'Encabezados PDF de ventas, compras y facturas',
    'summary': 'Encabezado compacto que se repite en cada página del PDF de presupuestos, pedidos y proformas de venta, solicitudes y órdenes de compra, y facturas y notas de crédito de cliente. En ventas también muestra etiquetas, teléfonos y la fecha de entrega con hora. El formato de papel global no se modifica. Las facturas de proveedor quedan como están. La localización argentina, si está instalada, conserva el encabezado legal y solo repite la identificación del cliente.',
    'version': '19.0.1.4.3',
    'category': 'Sales',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['sale', 'purchase', 'account'],
    'data': [
        'report/paperformat.xml',
        'views/sale_order_views.xml',
        'report/sale_report_templates.xml',
        'report/purchase_report_templates.xml',
        'report/invoice_report_templates.xml',
    ],
    'installable': True,
    'application': False,
}
