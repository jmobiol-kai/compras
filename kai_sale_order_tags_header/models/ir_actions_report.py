from odoo import models

# Quotation, customer preview / raw quote and proforma. Invoices keep the
# company paper format (base.paperformat_euro in these databases).
SALE_REPORT_NAMES = (
    'sale.report_saleorder',
    'sale.report_saleorder_raw',
    'sale.report_saleorder_pro_forma',
)


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def get_paperformat(self):
        if len(self) == 1 and self.report_name in SALE_REPORT_NAMES:
            paperformat = self.env.ref(
                'kai_sale_order_tags_header.paperformat_saleorder',
                raise_if_not_found=False,
            )
            if paperformat:
                return paperformat
        return super().get_paperformat()
