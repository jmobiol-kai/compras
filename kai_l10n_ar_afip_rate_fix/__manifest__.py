# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
{
    "name": "AFIP - Cotización: evitar error en PES",
    "summary": (
        "Oculta el botón Check rate en facturas en pesos (PES / moneda de la "
        "compañía) y evita el KeyError ResultGet cuando AFIP no devuelve "
        "cotización, mostrando un UserError claro sin escribir la tasa."
    ),
    "version": "19.0.1.0.0",
    "category": "Accounting/Accounting",
    "author": "Kaizendo",
    "website": "https://kaizendo.com.ar",
    "license": "LGPL-3",
    "depends": ["l10n_ar_afipws_fe"],
    "data": [
        "views/account_move_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
