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

Solo pedidos confirmados: sale y done. Odoo 19 guarda los pedidos bloqueados
en sale (no hay estado done en el selection estándar); done queda en el
filtro para no perder filas históricas. Los presupuestos draft y sent no
entran nunca, tampoco cancel, aunque un asistente anterior hubiera guardado
«Incluir presupuestos». No entran secciones, subsecciones ni notas
(display_type).

El asistente pide el proveedor antes de mostrar el listado (no se inventa
ni se filtra por supplier_rank: en esta base los proveedores están en
product.supplierinfo). «Generar orden de compra» crea de inmediato una sola
OC en borrador, con una línea por producto comprable (purchase_ok). La
cantidad es la del informe, en la unidad del proveedor o en la del producto.
El precio unitario de cada línea nueva es el costo del producto
(standard_price) de la compañía de la OC, pasado a la unidad de la línea y
a la moneda de la OC. No es el precio de venta ni la tarifa del proveedor.
Si el costo es cero, el precio queda en cero. El campo sigue siendo editable.
No se reescriben precios de compras ya creadas ni el costo del producto.
Los impuestos de compra y la posición fiscal se mantienen; un impuesto
incluido que la posición fiscal quite se descuenta para no sumar el IVA
dos veces. El tipo de recepción sale del default de la compañía
(purchase_stock).
El formulario que se abre es el de compras estándar y queda editable en
borrador (referencia de proveedor y diario de compras de la compañía). El
listado del informe sigue sin edición. No se tocan los readonly de una OC
confirmada o bloqueada, ni las reglas multi-compañía.

Cada línea de compra guarda qué líneas de venta cubre y en qué cantidad
(unidad del producto, misma compañía). El informe muestra demanda, cubierto
y pendiente, y abre esos pedidos. Un borrador, una solicitud enviada, una
compra por aprobar y una compra confirmada cuentan. Cancelar no borra el
vínculo, pero deja de cubrir; si la compra vuelve a borrador, cubre otra vez.
Bajar la cantidad de la línea de compra suelta el excedente desde el vínculo
más nuevo. Subirla no cubre más ventas. Cambiar el producto suelta los
vínculos. Bajar o subir la cantidad vendida no modifica la compra: lo que
sobre queda pendiente y se puede comprar; si lo cubierto supera a la venta,
el informe lo marca excedido y no genera otra compra por esa línea. No se
puede borrar una línea de venta que siga cubierta. Las compras anteriores
sin este vínculo no descuentan, aunque el origen diga la fecha de entrega.

«Anular y deshacer» está en la cotización que tiene vínculos del informe,
en borrador, enviada o cancelada. Cancela si sigue abierta, quita esos
vínculos y los productos de la compra, y la deja en borrador con el mismo
número y el mismo proveedor. No borra las ventas ni la orden, y no toca
la referencia de proveedor. La demanda queda libre. Cancelar con el botón
normal no borra líneas ni vínculos. Una orden confirmada, con recepción
hecha, factura o pago, no se deshace.
""",
    'version': '19.0.1.0.6',
    'category': 'Sales',
    'author': 'Kaizendo',
    'license': 'LGPL-3',
    'depends': ['sale', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'security/sale_po_allocation_rules.xml',
        'views/sale_category_delivery_line_views.xml',
        'views/sale_category_delivery_wizard_views.xml',
        'views/purchase_order_views.xml',
    ],
    'installable': True,
    'application': False,
}
