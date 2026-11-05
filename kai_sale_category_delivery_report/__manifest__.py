{
    'name': 'Productos por categoría y fecha de entrega',
    'summary': (
        'Informe de ventas por categoría y fecha de entrega (commitment_date), '
        'con generación de una orden de compra en borrador.'
    ),
    'description': """
Ventas → Informes → Productos por categoría y fecha de entrega.

El asistente pide una o más categorías de producto y un día de entrega.
Lista los productos de esas categorías (y de sus hijas) que están en líneas
de pedido de la compañía activa cuya fecha de entrega
(sale.order.commitment_date) cae ese día calendario, en la zona del usuario,
si no tiene en la de la compañía, y si no tiene en
America/Argentina/Buenos_Aires. La cantidad es la suma, expresada en la
unidad del producto.

Estados por defecto: sale y done. Odoo 19 guarda los pedidos bloqueados en
sale (no hay estado done en el selection estándar); done queda en el filtro
para no perder filas históricas. «Incluir presupuestos» suma draft y sent.
No entran secciones, subsecciones ni notas (display_type).

El asistente pide el proveedor antes de mostrar el listado (no se inventa
ni se filtra por supplier_rank: en esta base los proveedores están en
product.supplierinfo). «Generar orden de compra» crea de inmediato una sola
OC en borrador, con una línea por producto comprable (purchase_ok). La
cantidad es la del informe, en la unidad del proveedor o en la del producto.
El tipo de recepción sale del default de la compañía (purchase_stock).
""",
    'version': '19.0.1.0.1',
    'category': 'Sales',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['sale', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'views/sale_category_delivery_line_views.xml',
        'views/sale_category_delivery_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
