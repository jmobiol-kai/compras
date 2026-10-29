# Addons de Odoo

Este repositorio es una carpeta de addons. En el servidor, `addons_path` debe apuntar a la raíz de este repositorio, no a la carpeta de un módulo.

- `kai_onchange_journal`: fuerza la moneda de la orden de compra según la moneda del diario.
- `kai_purchase_requisition_reference_name`: muestra el acuerdo de compra como «PT00001 - referencia» y permite buscarlo por el campo `reference`.
- `kai_purchase_requisition_cost_sync`: sincroniza el `price_unit` de `purchase.requisition.line` desde `product.standard_price` (costo contable) cada vez que ese costo cambia, en todos los acuerdos abiertos (estado distinto de `cancel` y `done`).
- `kai_bank_statement_menu`: menú Contabilidad → Extractos bancarios, caja y tarjetas. Lista `account.bank.statement` de diarios banco, caja y crédito (sin sustituir la acción de core `account.action_bank_statement_tree`) y habilita el origen de extractos y la importación OCA en diarios de caja. Requiere en `addons_path` los módulos OCA `account_statement_base`, `account_reconcile_oca`, `account_statement_import_file` y `account_statement_import_sheet_file`.
- `kai_bill_attachment_preview`: en facturas de cliente, notas de crédito, facturas de proveedor y reembolsos, muestra el PDF adjunto al costado del formulario (layout COMBO de mail, pantallas XXL) también cuando el comprobante está publicado. Hereda `account.view_move_form` y quita el `state != 'draft'` de `o_attachment_preview`, y un parche JS sobre `mailLayout()` recupera el panel aunque OCA `web_responsive` desactive `FormRenderer.hasFile()`. Depende solo de `account`.
