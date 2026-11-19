{
    'name': 'Costo de reposición automático',
    'summary': (
        'Último precio neto de la factura de proveedor, roll-up de listas de '
        'materiales y contribución marginal por sucursal.'
    ),
    'description': """
Al publicar una factura de proveedor, actualiza la tarifa compartida
(product.supplierinfo sin compañía) con el precio neto de la línea.
El costo de reposición de un fabricado sale de su lista de materiales.

No escribe el precio de venta ni el costo contable. El margen de la
categoría (heredado del padre, o el del producto si tiene margen propio)
solo arma un precio sugerido de referencia.

Inventario → Productos → Precio sugerido vs. actual.
Inventario → Informes → Historial de costo de reposición.
Compras → Productos → Productos con costo 0 sin compras.
Contabilidad → Informes → Contribución marginal (también en Punto de venta).
""",
    'version': '19.0.1.4.4',
    'category': 'Inventory/Purchase',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': [
        'purchase',
        'mrp',
        'point_of_sale',
        'account',
        'product_replenishment_cost',
        'product_replenishment_cost_mrp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/margin_security.xml',
        'views/margin_contribution_views.xml',
        'views/zero_cost_views.xml',
        'views/category_margin_views.xml',
        'views/replenishment_cost_history_views.xml',
    ],
    'installable': True,
    'application': False,
}
