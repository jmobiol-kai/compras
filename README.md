# Addons de Odoo

Este repositorio es una carpeta de addons. En el servidor, `addons_path` debe apuntar a la raíz de este repositorio, no a la carpeta de un módulo.

- `kai_onchange_journal`: fuerza la moneda de la orden de compra según la moneda del diario.
- `kai_purchase_requisition_reference_name`: muestra el acuerdo de compra como «PT00001 - referencia» y permite buscarlo por el campo `reference`.
- `kai_bank_statement_menu`: menú Contabilidad → Extractos bancarios. Abre el listado clásico de `account.bank.statement` (`account.action_bank_statement_tree`). Requiere en `addons_path` los módulos OCA `account_statement_base` y `account_reconcile_oca`.
