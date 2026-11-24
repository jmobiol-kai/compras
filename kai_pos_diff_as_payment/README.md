# PdV - Diferencias bancarias como pagos

Módulo de Odoo 19 CE (`kai_pos_diff_as_payment`).

Al cerrar una sesión de Punto de Venta con diferencia de conteo en un método
de pago bancario (Mercado Pago, Provincia, etc.), el estándar de
`point_of_sale` (`pos.session._create_diff_account_move_for_split_payment_method`)
crea un asiento suelto en el diario del banco. El tablero contable lo muestra
como «Operaciones misceláneas», porque el apunte no tiene `payment_id` ni
`statement_line_id`.

Este módulo reemplaza ese asiento por un `account.payment` publicado en el
mismo diario:

- inbound si sobra, outbound si falta
- cuenta pendiente (outstanding) = cuenta del banco
- destino = cuenta de ganancia o pérdida por diferencia del diario
- memo: `Diferencia de cierre <sesión>`
- vinculado a la sesión y al método de pago del PdV

El efectivo sigue el comportamiento estándar (línea de extracto / diferencia
de caja).
