from odoo import fields, models, tools


class KaiMarginContributionReport(models.Model):
    """Contribución marginal mensual por compañía y producto.

    Ventas facturadas: líneas de producto de facturas y notas de crédito de
    cliente, en moneda de la compañía (``-balance`` de cuentas de ingreso).
    El CMV de esas facturas es el saldo de las líneas ``display_type = cogs``
    imputadas a una cuenta de gasto. La contrapartida contra existencias no
    se suma: las dos líneas se netean.

    POS no facturado: ``price_subtotal`` y ``total_cost`` de la línea, pasados
    a moneda de la compañía con ``currency_rate``. El pedido facturado
    (``account_move`` cargado) no entra: ya está en la factura. El asiento de
    cierre de sesión es ``move_type = entry`` y tampoco entra, así que no se
    cuenta dos veces.

    El mes del POS se calcula en America/Argentina/Buenos_Aires. El de la
    factura es ``invoice_date``, que ya es una fecha local.
    """

    _name = 'kai.margin.contribution.report'
    _description = 'Contribución marginal'
    _auto = False
    _order = 'date desc, company_id, product_id'
    _rec_name = 'product_id'

    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True)
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string='Plantilla', readonly=True)
    categ_id = fields.Many2one('product.category', string='Categoría', readonly=True)
    date = fields.Date(string='Mes', readonly=True)
    sales_amount = fields.Monetary(string='Ventas netas', readonly=True, currency_field='currency_id')
    cogs_amount = fields.Monetary(string='CMV', readonly=True, currency_field='currency_id')
    margin_amount = fields.Monetary(
        string='Contribución marginal', readonly=True, currency_field='currency_id',
    )
    margin_percent = fields.Float(
        string='Contribución %',
        readonly=True,
        digits=(16, 2),
        aggregator='avg',
        help=(
            'Porcentaje de la fila (compañía, producto y mes). '
            'En el pivot, al agrupar, el promedio no reemplaza al porcentaje recalculado.'
        ),
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            'CREATE OR REPLACE VIEW %s AS (%s)' % (self._table, self._query())
        )

    def _query(self):
        return """
            SELECT
                row_number() OVER (
                    ORDER BY src.company_id, src.product_id, src.month_date
                ) AS id,
                src.company_id AS company_id,
                company.currency_id AS currency_id,
                src.product_id AS product_id,
                product.product_tmpl_id AS product_tmpl_id,
                template.categ_id AS categ_id,
                src.month_date AS date,
                SUM(src.sales_amount) AS sales_amount,
                SUM(src.cogs_amount) AS cogs_amount,
                SUM(src.sales_amount) - SUM(src.cogs_amount) AS margin_amount,
                CASE
                    WHEN ABS(SUM(src.sales_amount)) < 0.0000001 THEN 0
                    ELSE (SUM(src.sales_amount) - SUM(src.cogs_amount))
                         / SUM(src.sales_amount) * 100
                END AS margin_percent
            FROM (
                SELECT
                    move.company_id AS company_id,
                    line.product_id AS product_id,
                    date_trunc(
                        'month', COALESCE(move.invoice_date, move.date)
                    )::date AS month_date,
                    -line.balance AS sales_amount,
                    0::numeric AS cogs_amount
                FROM account_move_line line
                JOIN account_move move ON move.id = line.move_id
                JOIN account_account account ON account.id = line.account_id
                WHERE move.state = 'posted'
                  AND move.move_type IN ('out_invoice', 'out_refund')
                  AND line.display_type = 'product'
                  AND line.product_id IS NOT NULL
                  AND account.account_type LIKE 'income%'

                UNION ALL

                SELECT
                    move.company_id AS company_id,
                    line.product_id AS product_id,
                    date_trunc(
                        'month', COALESCE(move.invoice_date, move.date)
                    )::date AS month_date,
                    0::numeric AS sales_amount,
                    line.balance AS cogs_amount
                FROM account_move_line line
                JOIN account_move move ON move.id = line.move_id
                JOIN account_account account ON account.id = line.account_id
                WHERE move.state = 'posted'
                  AND move.move_type IN ('out_invoice', 'out_refund')
                  AND line.display_type = 'cogs'
                  AND line.product_id IS NOT NULL
                  AND account.account_type LIKE 'expense%'

                UNION ALL

                SELECT
                    pos_order.company_id AS company_id,
                    pos_line.product_id AS product_id,
                    date_trunc(
                        'month',
                        pos_order.date_order AT TIME ZONE 'UTC'
                            AT TIME ZONE 'America/Argentina/Buenos_Aires'
                    )::date AS month_date,
                    CASE
                        WHEN pos_order.currency_rate IS NULL
                             OR pos_order.currency_rate = 0
                        THEN signed.sales_amount
                        ELSE signed.sales_amount / pos_order.currency_rate
                    END AS sales_amount,
                    CASE
                        WHEN pos_order.currency_rate IS NULL
                             OR pos_order.currency_rate = 0
                        THEN signed.cogs_amount
                        ELSE signed.cogs_amount / pos_order.currency_rate
                    END AS cogs_amount
                FROM pos_order_line pos_line
                JOIN pos_order ON pos_order.id = pos_line.order_id
                JOIN LATERAL (
                    SELECT
                        CASE
                            WHEN pos_order.is_refund THEN -ABS(pos_line.price_subtotal)
                            ELSE pos_line.price_subtotal
                        END AS sales_amount,
                        CASE
                            WHEN pos_order.is_refund THEN -ABS(COALESCE(pos_line.total_cost, 0))
                            ELSE COALESCE(pos_line.total_cost, 0)
                        END AS cogs_amount
                ) signed ON TRUE
                WHERE pos_order.state IN ('paid', 'done')
                  AND pos_order.account_move IS NULL
                  AND pos_line.product_id IS NOT NULL
                  AND pos_order.date_order IS NOT NULL
            ) src
            JOIN res_company company ON company.id = src.company_id
            JOIN product_product product ON product.id = src.product_id
            JOIN product_template template ON template.id = product.product_tmpl_id
            WHERE src.month_date IS NOT NULL
            GROUP BY
                src.company_id,
                company.currency_id,
                src.product_id,
                product.product_tmpl_id,
                template.categ_id,
                src.month_date
        """
