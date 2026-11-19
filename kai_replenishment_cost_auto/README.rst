Costo de reposición automático
==============================

Módulo ``kai_replenishment_cost_auto`` (19.0.1.4.4, LGPL-3) para un grupo
con empresa central y sucursales, mismo CUIT. El costo de reposición es uno
solo para todo el grupo y sirve de referencia para el precio. El módulo no
escribe el precio de venta (``list_price``) ni el costo contable
(``standard_price``, FIFO en tiempo real).

Depende de ``purchase``, ``mrp``, ``point_of_sale``, ``account`` y de los
módulos de Adhoc en la rama 19.0 de ``ingadhoc/product``:

* ``product_replenishment_cost`` **19.0.1.3.0** (commit ``b0b2074``, el que
  está en el servidor) o posterior. El costo no está almacenado. Con tipo
  «Último precio de proveedor» toma la tarifa cuya ``last_date_price_updated``
  es la más nueva. ``net_price`` es ``price`` salvo que la tarifa tenga una
  regla de recargo. En 19.0.1.3.0 no existe ``supplier_uom_id`` y el costo
  usa ``supplier_price`` sin convertir la unidad: por eso la tarifa se guarda
  ya en la unidad del producto. Desde 19.0.1.7.0 Adhoc convierte la unidad
  de la tarifa; como la nuestra es la del producto, el resultado es el mismo.
* ``product_replenishment_cost_mrp`` 19.0.1.0.0 (el que acompaña a 1.3.0) o
  posterior. Tipo «Basado en LdM». El costo es el roll-up de la lista de
  materiales (``bom.explode``), también sin almacenar. 19.0.1.0.0 no marca
  el campo como ``recursive``; este módulo sí, para que un lote de dos niveles
  no devuelva 0 en el componente. Esa es la cascada del costo: se lee, no
  se graba.

Margen de referencia y precio sugerido
--------------------------------------

En la categoría hay «Definir margen», un margen % y un recargo. Si
«Definir margen» está desmarcado, se heredan los de la categoría padre.
En la raíz, sin definir, el margen es 0 y el recargo es 0.

En el producto, «Margen propio» usa el margen y el recargo cargados ahí.
Si está desmarcado, el precio sugerido usa el margen efectivo de la
categoría. La fórmula es el costo de reposición de la compañía principal
(en este cliente, Blinis SA) × (1 + margen %) + recargo, más el IVA si el
impuesto está incluido en el precio. En un fabricado ese costo ya es el
roll-up de la lista de materiales.

El precio sugerido y la diferencia contra el precio de venta (importe y %)
no se almacenan: se calculan al abrir el formulario o la lista. Inventario
→ Productos → «Precio sugerido vs. actual» se puede filtrar por categoría
y exportar. Inventario → Configuración → Productos → «Importar márgenes
por categoría» carga líneas ``nombre completo;margen;recargo`` y solo
escribe la categoría.

Historial de costo
------------------

Cada línea de factura de proveedor con precio mayor que cero deja una fila
en el historial, aunque el costo de reposición no cambie. Ahí se ve el
precio de cada compra (dos proveedores al mismo precio son dos filas) y no
solo el último de la pestaña Compras. La fecha es la de la factura. El
precio unitario está en la unidad del producto y en la moneda de la
compañía principal. También se guardan el costo anterior, el nuevo y la
variación en importe y en %.

Si ese costo mueve el roll-up de un fabricado, se agrega otra fila con
origen «LdM», apuntando al insumo y a la factura. El costo del insumo y
el del fabricado se leen por separado: en el mismo lote, el cómputo de
Adhoc devuelve 0 para el componente y la fila no se escribía. Si aun así
el costo en vivo no se mueve, el roll-up se calcula con las cantidades de
la lista de materiales. Volver la factura a borrador o cancelarla marca
esas filas como anuladas y no revierte la tarifa. En la ficha del producto hay un botón «Historial de costo».
Inventario → Informes → «Historial de costo de reposición» tiene lista,
pivot y gráfico, filtros por producto, categoría, proveedor, sucursal y
fecha, y se exporta. Con la compañía principal entre las compañías activas
se leen todas las sucursales; si no, solo las propias. «Cargar desde
facturas publicadas» reconstruye el historial en orden de fecha, sin tocar
el costo actual.

CMV estimado
------------

Ventas anteriores a la valuación en tiempo real no tienen líneas de CMV:
el informe las mostraba con CMV 0 y contribución 100 %. Para cada línea
de factura de cliente o de POS no facturado, si el producto es almacenable
y no hay CMV contable (en el POS, ``total_cost`` en cero), se estima
cantidad en la unidad del producto por un costo a la fecha de la venta.
Una nota de crédito resta solo si tiene una devolución de stock hecha;
un reembolso de precio, sin retorno, no mueve el CMV estimado. En un
producto comprado el orden es: historial vigente anterior o igual, si no
el primer historial posterior que venga de una factura (una fila LdM
posterior no cuenta), si no la tarifa compartida y si no el costo
contable. En un fabricado: historial anterior o igual (factura o LdM),
si no la lista de materiales del grupo (sin compañía o de la empresa
central, no la de la sucursal) a esa fecha, si no la tarifa compartida
y si no el costo contable de la empresa central. El costo de cada
insumo sale de esa misma tarifa compartida, no del ``standard_price``
de la sucursal. No se usa una fila LdM posterior: es un roll-up parcial. Servicios y
consumibles no valuados quedan en cero. No se crean asientos.

El informe muestra el CMV contable, el estimado, el total y la
contribución sobre el total, más el origen del costo y el filtro «Con
CMV estimado». Abre agrupado por compañía, con «Este mes», «Mes anterior»
y el rango de fechas. El pivot arranca con ventas netas, CMV total,
contribución y contribución %.

Decisiones
----------

* El disparador es ``account.move.action_post`` de una factura de proveedor
  (``in_invoice``), no la confirmación de la orden de compra. El precio
  pagado está en la factura, haya o no orden vinculada. Core, en
  ``purchase.order._add_supplier_to_product``, solo crea tarifa si el
  proveedor es nuevo y no actualiza la existente: este módulo crea o
  actualiza la tarifa compartida (``company_id`` vacío).
* Precio guardado: ``price_subtotal / cantidad`` (ya tiene el descuento y
  no tiene IVA), convertido a la unidad del producto y a la moneda de la
  compañía que publica. La tarifa queda en esa unidad y con descuento 0.
  Si la tarifa tiene una regla de Adhoc, se guarda el precio bruto cuya
  regla devuelve ese neto.
* La fecha de la tarifa es el fin del día de ``invoice_date`` (y un
  microsegundo más si otra tarifa compartida ya tiene esa misma marca), no
  la hora de publicación. Así una factura vieja no pisa un precio más nuevo.
  Si en el mismo producto hay varias líneas con precio > 0, queda la última
  en secuencia.
* Las líneas en 0, sin producto, de sección o de anticipo se ignoran.
* Las notas de crédito de proveedor (``in_refund``) no actualizan la tarifa
  y no bajan el costo. Cancelar la factura o volverla a borrador tampoco
  revierte la tarifa: recuerda el último precio que se publicó.
* Para el costo, la tarifa compartida gana sobre una tarifa de una sola
  sucursal. Si el producto estaba en «Manual» o «Precio del proveedor
  principal», pasa a «Último precio de proveedor». «Basado en LdM» no se
  cambia.
* Sin ninguna tarifa con precio > 0, el costo de reposición (solo lectura)
  usa el ``standard_price`` de la compañía en curso. Adhoc no hace ese
  reemplazo: deja el costo en 0.
* El roll-up de una lista de materiales se resuelve al leer el costo de
  reposición del fabricado. El módulo no recorre la LdM para escribir
  precios.
* El cron de Adhoc «Update Cost from Replenishment Cost» copia el costo de
  reposición al costo contable. Con FIFO en tiempo real tiene que seguir
  desactivado. Este módulo no lo dispara.

Productos con costo 0 sin compras
---------------------------------

Compras → Productos → «Productos con costo 0 sin compras».

Lista, exportable, de productos comprables de tipo bienes (almacenables y
consumibles: en Odoo 19 los dos son ``type = consu``). Entra el que no tiene
ninguna tarifa con precio > 0 y cuyo costo de reposición es 0. Un producto
por fila. ``standard_price`` es por compañía: si alguna sucursal lo tiene
mayor que cero, el producto no entra. Un fabricado entra solo si el roll-up
es 0 en todas las compañías. Los servicios no entran.

Contribución marginal
---------------------

Contabilidad → Informes, y Punto de venta → Informes. Pivot, gráfico y lista,
con filtros por compañía, producto, categoría y mes. La regla de registro
limita las filas a las compañías activas del usuario.

Cada fila es compañía + producto + mes + origen del costo estimado:

* Ventas facturadas: ``-balance`` de las líneas de producto de facturas y
  notas de crédito de cliente cuya cuenta es de ingreso. Es moneda de la
  compañía, neta de IVA.
* CMV de esas facturas: ``balance`` de las líneas ``display_type = cogs``
  con cuenta de gasto (``expense*``). La contrapartida contra la cuenta de
  existencias no se suma, porque las dos líneas se netean. Con valuación
  perpetua ese importe es el costo FIFO (u otro método) que armó Odoo al
  publicar la factura.
* POS no facturado: ``price_subtotal`` y ``total_cost`` de
  ``pos.order.line``, en pedidos ``paid`` o ``done`` sin ``account_move``,
  pasados a moneda de la compañía con ``currency_rate``. Un reembolso de POS
  resta. El mes usa ``America/Argentina/Buenos_Aires``.
* El pedido de POS ya facturado no entra por el ticket: entra por la factura.
  El asiento de cierre de sesión es un asiento ``entry``, no una factura, y
  tampoco entra. No hay doble conteo entre POS facturado y no facturado.
* Si no hay CMV contable, el CMV estimado se suma aparte. La contribución
  usa el CMV total (contable + estimado). Ver «CMV estimado».

El porcentaje de la lista es el de esa fila. En el pivot, al agrupar, el
promedio del porcentaje no reemplaza a ``(ventas - CMV total) / ventas``.

Cómo correr los tests
---------------------

Los tests son ``TransactionCase`` con etiqueta ``post_install``. Hacen falta
Odoo 19 y los tres módulos de Adhoc en el ``addons_path``. En un CI que no
los tenga, estos tests no se pueden instalar: el manifiesto no carga.

::

    odoo-bin -c odoo.conf -d test_kai --test-enable --stop-after-init \
        -i kai_replenishment_cost_auto \
        --addons-path=/ruta/odoo/addons,/ruta/ingadhoc/product,/ruta/compras

Con el módulo ya instalado:

::

    odoo-bin -c odoo.conf -d test_kai --test-enable --stop-after-init \
        -u kai_replenishment_cost_auto \
        --test-tags /kai_replenishment_cost_auto

Cubren: actualización de una tarifa existente al publicar la factura
(unidad docena, descuento, contacto hijo, línea en 0, nota de crédito y
vuelta a borrador sin revertir, factura más vieja que no pisa), roll-up de
LdM de dos niveles (el costo sube y el ``list_price`` queda igual),
``standard_price`` intacto, precio sugerido con margen heredado y con
margen propio, el historial (dos proveedores al mismo precio, cascada de
LdM, anulación sin revertir el costo y carga desde facturas ya publicadas),
el CMV estimado (historial anterior, solo posterior, sin historial, con
CMV contable y nota de crédito),
el listado de costo 0, y el reporte (factura con CMV, POS no
facturado, POS facturado que no se duplica, reembolso de POS).

Limitaciones
------------

* No es un promedio ponderado: es el último precio de factura con fecha
  mayor o igual a la tarifa de ese proveedor.
* Un producto «Basado en LdM» que además se compra no toma el precio de la
  factura como costo. El roll-up sigue mandando.
* El precio sugerido usa el costo de reposición de la compañía principal y,
  en un fabricado, la lista de materiales que ``_bom_find`` elige para esa
  compañía. No reemplaza al precio de venta. Las listas de precios se arman
  sobre ese precio de venta, cargado a mano.
* El costo de reposición vive en la plantilla. En un producto con variantes,
  la tarifa es por variante, pero el último precio de cualquier variante
  puede definir el costo de toda la plantilla.
* No entran costos en destino ni diferencias de precio de la recepción.
* El CMV del POS no facturado es el ``total_cost`` que Odoo guardó en la
  línea (FIFO si el punto de venta ya lo calculó desde el movimiento de
  stock). Puede no coincidir al centavo con el asiento de cierre de sesión.
* Una factura en otra moneda que la de la compañía se convierte al tipo de
  cambio de la fecha de factura. El reporte de POS asume el ``currency_rate``
  de Odoo (compañía → moneda del pedido).
* Anticipos de cliente que no estén en una cuenta de ingreso no entran como
  venta. Los que sí estén en una cuenta de ingreso, sí.
* El cron de Adhoc que copia reposición a ``standard_price`` sigue pudiendo
  pisar el FIFO si alguien lo activa.
