# PdV - Pagos por método y diario

Informe pivot de pagos del Punto de venta, agrupados por PdV, diario de
facturación (Ventas FE / Ventas X) y tipo de medio (efectivo / electrónico),
con exportación a planilla Excel.

## Uso

Punto de venta > Reportes > Pagos por método y diario.

El acceso no lo dan los grupos del PdV: hay que marcar a cada usuario el
privilegio **Pagos por método y diario** en Ajustes > Usuarios >
Derechos de acceso, sección Ventas (desplegable; "No" o "Ver reporte de
pagos por método y diario"). En la instalación solo se asigna al
administrador interno (`base.user_admin`).

En el pivot, las columnas por defecto agrupan por **Tipo de medio**
(Efectivo / Electrónico), expandible a Método de pago. El tipo de medio
sigue la misma regla que la planilla: efectivo si el método está marcado
para recuento de caja (`is_cash_count`) o usa un diario tipo `cash`; el
resto es electrónico.

El diario se toma de la factura de la orden. Si todavía no hay factura, se
usa el diario de lote (X) cuando la orden está marcada `use_batch_journal`,
o el diario de facturación del PdV.

No depende de `msb_pos_facturacion_lotes`: si ese módulo está instalado se
respetan `use_batch_journal` y `default_journalx`; si no, queda el diario
de factura del PdV.

## Exportar planilla

El botón **Exportar planilla** está en la barra del pivot, al lado de
la descarga estándar, y también en la vista lista del informe. El asistente pide fecha desde y
hasta (por defecto el mes en curso) y descarga un Excel con un bloque por
PdV, en el orden de secuencia o, si no hay secuencia, Mañana / Tarde /
Buffet: EFECTIVO, MEDIOS ELECTRÓNICOS, VENTAS FE, VENTAS X; un renglón
por cada día del período (aunque no haya ventas) y una fila TOTAL.

VENTAS FE usa el diario Ventas FE del PdV (`invoice_journal_id`);
VENTAS X el resto (diario Ventas X). Por día y PdV, efectivo + electrónicos
es igual a Ventas FE + Ventas X. Se excluyen las órdenes canceladas.
La fecha de cada renglón es `payment_date_date` (zona horaria de la
compañía).

## Instalación

Instalar `kai_pos_payment_report`. El `post_init` (o el script de
migración al actualizar a 19.0.1.2.0) completa los campos almacenados
de los pagos históricos.
