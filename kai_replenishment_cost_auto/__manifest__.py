{
    'name': 'Costo de reposición automático',
    'summary': (
        'Último precio neto de la factura de proveedor, roll-up de listas de '
        'materiales y contribución marginal por sucursal.'
    ),
    'description': """
Al publicar una factura de proveedor, actualiza la tarifa compartida
(product.supplierinfo sin compañía) con el precio neto de la línea y
recalcula el precio de venta de los productos que usan ese insumo en una
lista de materiales, si tienen margen en Precio planificado.

No modifica el costo contable (standard_price). La valuación FIFO queda
como está.

Compras → Productos → Productos con costo 0 sin compras.
Contabilidad → Informes → Contribución marginal (también en Punto de venta).
""",
    'version': '19.0.1.0.0',
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
        'product_planned_price',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/margin_security.xml',
        'views/margin_contribution_views.xml',
        'views/zero_cost_views.xml',
    ],
    'installable': True,
    'application': False,
}
