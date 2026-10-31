from odoo import api, models


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    @api.depends(
        'name',
        'delivery_type',
        'fixed_price',
        'product_id.list_price',
        'currency_id',
        'product_id.currency_id',
    )
    def _compute_display_name(self):
        """Many2one label: carrier name and its price, same idea as purchase agreements."""
        for carrier in self:
            amount = carrier._kai_format_price(carrier._kai_selection_price())
            carrier.display_name = f"{carrier.name or ''} - {amount}"

    def _kai_selection_price(self):
        """Price shown beside the method name.

        Fixed methods keep their price on ``fixed_price``, which Odoo syncs
        with the delivery product list price. Other providers have no single
        fixed price, so the delivery product list price is used instead.
        """
        self.ensure_one()
        if self.delivery_type == 'fixed' or not self.product_id:
            return self.fixed_price
        return self.product_id.list_price

    def _kai_format_price(self, amount):
        self.ensure_one()
        currency = self.currency_id or self.env.company.currency_id
        if currency:
            return currency.format(amount)
        return f"{amount:.2f}"
