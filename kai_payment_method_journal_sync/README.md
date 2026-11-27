# Pagos: sincronizar método al cambiar el diario

Módulo de Odoo 19 (`kai_payment_method_journal_sync` 19.0.1.0.1, LGPL-3).

Al cambiar el diario de un pago en borrador, `payment_method_line_id` pasa a
la línea del diario nuevo que usa el mismo método. No crea diarios, líneas
de método ni cuentas, y no cambia la compañía del pago más allá de lo que
ya hace `account_payment_pro`.

## Síntoma

En Blinis, el pago de proveedor 2440 (compañía Fisa) falló al confirmar:

> El método de pago seleccionado no está disponible para este pago, elija otro.

Es la traducción `es_419` del constraint de Odoo 19
`account.payment._check_payment_method_line_id`. El pago se había guardado
con el diario Banco Mercado Pago (compañía Blinis SA) y su línea
Transferencia. Después el diario pasó a Banco Santander, también de
Blinis SA, pero «Cheques propios» que quedó grabado era la línea del
diario Mercado Pago. Las dos líneas se llaman igual. Al confirmar,
`payment_method_line_id.journal_id` no coincide con `payment.journal_id`.

Fisa no tiene diarios bancarios y paga con los de Blinis SA, que es lo
que habilita `account_payment_pro`. No hace falta un diario bancario para
Fisa. El hermano `kai_payment_pro_branch_company` solo evita un
AccessError al cambiar el diario en una sucursal; este módulo no lo toca.

## Por qué el core no lo resuelve

`payment_method_line_id` es un many2one calculado, almacenado y editable.
`_compute_payment_method_line_id` depende de las líneas disponibles del
diario (el dominio sí se actualiza) y elige, en este orden, el default
del partner, la línea actual si sigue disponible, o la primera. Nunca
busca en el diario nuevo la línea con el mismo `payment_method_id` o el
mismo código (`own_checks`, `manual`, etc.).

Como el campo es editable, si el mismo `write` trae el diario nuevo y el
id del método viejo, ese id le gana al cómputo. El constraint solo está
declarado sobre `payment_method_line_id`, y compara el diario de la línea
con el del pago. Hay que corregir los vals antes de `super().write` y
`super().create`: un arreglo posterior llega tarde si el constraint ya
saltó.

## Criterio

`_kai_sync_payment_method_line_to_journal` devuelve la línea del diario
destino:

1. Si no hay diario, no toca el pago.
2. Si la línea no tiene diario, o ya es del diario destino y está entre
   las disponibles para ese `payment_type`, la deja.
3. Si no, busca en las líneas del diario nuevo
   (`journal._get_available_payment_method_lines`, con
   `_get_payment_method_codes_to_exclude` cuando el pago ya existe):
   1. la del mismo `payment_method_id`;
   2. si no, la del mismo código y un `payment_type` compatible;
   3. si el pago tiene `l10n_latam_new_check_ids`, o la línea origen era
      `own_checks` / `new_third_party_checks`, una línea de ese subtipo
      en el diario nuevo, para que `action_post` de `l10n_latam_check` no
      borre los cheques;
   4. si no, la primera disponible;
   5. si no hay ninguna, vacío.

Eso corre en el cómputo (el onchange del diario), en `create` y `write`
antes del `super()`, y al inicio de `action_post` para borradores que
todavía tengan un método de otro diario. El default del partner sigue
valiendo en un pago nuevo sin método, y cuando la línea ya es del diario
actual. Los pagos ya confirmados no se reescriben.

## Instalación

Actualizar el repositorio `compras` en el `addons_path` e instalar
`kai_payment_method_journal_sync` en la base. Depende de
`account_payment_pro` (y, a través de ese módulo, de `l10n_latam_check`).

En producción, solo con autorización de Juan y con un respaldo previo.
Este cambio no se instala solo.

## Cómo correr los tests

Son `TransactionCase` con etiqueta `post_install`. No heredan
`AccountTestInvoicingCommon` ni `UomCommon`: esa cadena crea un usuario
de test (`BaseCommon.setup_independent_user`) y después
`UomCommon` hace `uom_dozen.active = True`. En Odoo 19 esa asignación
llama a `write()`, y `write()` controla el acceso antes de mirar si el
valor cambió. En 00blinis la escritura de `uom.uom` no la da
`uom.group_uom` sino un grupo custom, así que la suite corre como
superusuario (`TransactionCase`) y no depende de los grupos de la base.
Hace falta Odoo 19 y `account_payment_pro` con sus dependencias en el
`addons_path` (en particular `l10n_latam_check`, por los cheques). Sin
eso el módulo no se puede instalar y los tests no corren.

```
odoo-bin -c odoo.conf -d test_kai --test-enable --stop-after-init \
    -i kai_payment_method_journal_sync \
    --addons-path=/ruta/odoo/addons,/ruta/ingadhoc/account-payment,/ruta/compras
```

Con el módulo ya instalado:

```
odoo-bin -c odoo.conf -d test_kai --test-enable --stop-after-init \
    -u kai_payment_method_journal_sync \
    --test-tags /kai_payment_method_journal_sync
```

Cubren: cambiar de diario conserva `own_checks` del diario nuevo (no la
primera línea, si esa es Transferencia); el write conjunto del pago 2440
(diario nuevo + «Cheques propios» del diario viejo) no dispara el
constraint y se puede confirmar; si el diario nuevo no tiene
`own_checks`, queda la primera línea; los cheques cargados siguen al
pasar a un diario que también tiene `own_checks` y la confirmación no los
borra; el default del partner no pisa ese mapeo, y sí se usa en un pago
nuevo sin método; el `create` con un método de otro diario; un write de
varios pagos asigna la línea de cada diario; el cómputo en memoria (el
onchange) mapea igual.
