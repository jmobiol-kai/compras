# AFIP - Cotización: evitar error en PES

Módulo de Odoo 19 CE (`kai_l10n_ar_afip_rate_fix`).

Puente sobre `l10n_ar_afipws_fe` (fork OnlyOne / ingadhoc). No parchea
pyafipws ni el árbol de `odoo-argentina-ce`.

Problema: el botón "Check rate" de la factura llama a
`FEParamGetCotizacion` también cuando la moneda es ARS (código AFIP `PES`).
AFIP no devuelve `ResultGet` para PES, y pyafipws termina en
`KeyError: 'ResultGet'`.

Este módulo:

- oculta el botón si la moneda es PES o es la moneda de la compañía
- si igual se llama el método en ARS/PES, deja la tasa en 1, avisa en el
  chatter y muestra una notificación, sin consultar AFIP
- para monedas extranjeras, consulta AFIP de forma segura: si falta
  `ResultGet`, lanza un `UserError` con el mensaje de AFIP y no escribe la
  tasa

Dependencia: `l10n_ar_afipws_fe`.
