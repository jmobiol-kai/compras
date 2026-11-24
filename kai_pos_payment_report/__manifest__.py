# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
{
    "name": "PdV - Pagos por método y diario",
    "summary": (
        "Informe pivot de pagos de PdV agrupados por punto de venta, "
        "diario de facturación (Ventas FE / Ventas X) y método de pago, "
        "con exportación a planilla Excel."
    ),
    "version": "19.0.1.2.2",
    "category": "Sales/Point of Sale",
    "author": "Kaizendo",
    "website": "https://kaizendo.com.ar",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "account"],
    "data": [
        "security/pos_payment_report_security.xml",
        "security/ir.model.access.csv",
        "views/pos_payment_report_views.xml",
        "wizard/pos_payment_report_export_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "assets": {
        "web.assets_backend": [
            "kai_pos_payment_report/static/src/views/kai_pos_payment_pivot.js",
            "kai_pos_payment_report/static/src/views/kai_pos_payment_pivot.xml",
        ],
    },
    "auto_install": False,
}
