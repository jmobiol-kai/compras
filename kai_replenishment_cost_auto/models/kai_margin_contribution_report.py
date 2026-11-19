from odoo import fields, models, tools


class KaiMarginContributionReport(models.Model):
    """Contribución marginal mensual por compañía y producto.

    Ventas facturadas: líneas de producto de facturas y notas de crédito de
    cliente, en moneda de la compañía (``-balance`` de cuentas de ingreso).
    El CMV contable de esas facturas es el saldo de las líneas
    ``display_type = cogs`` imputadas a una cuenta de gasto. La contrapartida
    contra existencias no se suma: las dos líneas se netean.

    Si el producto es almacenable y esa venta no tiene CMV contable, se
    estima cantidad en la unidad del producto por un costo a la fecha.
    La nota de crédito resta solo cuando hay una devolución de stock.
    En un fabricado, la lista de materiales a esa fecha se usa antes que
    un historial posterior. No se crean asientos.

    POS no facturado: ``price_subtotal`` y ``total_cost`` de la línea, pasados
    a moneda de la compañía con ``currency_rate``. El pedido facturado
    (``account_move`` cargado) no entra: ya está en la factura. El asiento de
    cierre de sesión es ``move_type = entry`` y tampoco entra, así que no se
    cuenta dos veces. Si ``total_cost`` es 0, se estima igual que en la factura.

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
    cogs_amount = fields.Monetary(
        string='CMV contable', readonly=True, currency_field='currency_id',
    )
    cogs_estimated = fields.Monetary(
        string='CMV estimado', readonly=True, currency_field='currency_id',
    )
    cogs_total = fields.Monetary(
        string='CMV total', readonly=True, currency_field='currency_id',
    )
    margin_amount = fields.Monetary(
        string='Contribución', readonly=True, currency_field='currency_id',
    )
    margin_percent = fields.Float(
        string='Contribución %',
        readonly=True,
        digits=(16, 2),
        aggregator='avg',
        help=(
            'Porcentaje de la fila: (ventas - CMV total) / ventas. '
            'El CMV total suma el contable y el estimado. '
            'En el pivot, al agrupar, el promedio no reemplaza al porcentaje recalculado.'
        ),
    )
    has_estimated_cogs = fields.Boolean(string='Con CMV estimado', readonly=True)
    cost_origin = fields.Selection(
        [
            ('history_before', 'Historial anterior'),
            ('history_after', 'Historial posterior'),
            ('replenishment', 'Reposición actual'),
            ('standard', 'Estándar'),
            ('bom', 'LdM'),
        ],
        string='Origen del costo',
        readonly=True,
    )

    def init(self):
        # La vista depende de las funciones: se baja primero.
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            "DROP FUNCTION IF EXISTS kai_margin_unit_cost(integer, date, integer, integer, integer, integer[])"
        )
        self.env.cr.execute(
            "DROP FUNCTION IF EXISTS kai_margin_convert_currency(numeric, integer, integer, integer, date)"
        )
        statements = [
            statement.strip()
            for statement in self._cost_function_sql().split('\n-- STATEMENT --\n')
            if statement.strip()
        ]
        # La conversión tiene que existir antes de que se ejecute el costo.
        statements.sort(key=lambda statement: statement.startswith(
            'CREATE OR REPLACE FUNCTION kai_margin_convert_currency'
        ), reverse=True)
        for statement in statements:
            self.env.cr.execute(statement)
        self.env.cr.execute(
            'CREATE OR REPLACE VIEW %s AS (%s)' % (self._table, self._query())
        )

    def _cost_function_sql(self):
        # El costo sale en moneda de la compañía principal. La vista lo pasa
        # a la moneda de la sucursal si hace falta. No escribe asientos.
        return r"""
CREATE OR REPLACE FUNCTION kai_margin_unit_cost(
    p_product_id integer,
    p_date date,
    p_company_id integer,
    p_main_company_id integer,
    p_depth integer DEFAULT 0,
    p_stack integer[] DEFAULT ARRAY[]::integer[]
) RETURNS TABLE(cost numeric, origin varchar) AS $$
DECLARE
    v_cost numeric;
    v_origin varchar;
    v_tmpl integer;
    v_type varchar;
    v_bom_id integer;
    v_has_bom boolean;
    v_bom_qty numeric;
    v_bom_uom integer;
    v_product_uom integer;
    v_line record;
    v_comp_cost numeric;
    v_total numeric;
    v_qty numeric;
    v_from_factor numeric;
    v_to_factor numeric;
    v_seller_price numeric;
    v_seller_currency integer;
    v_main_currency integer;
    v_company_currency integer;
    v_standard jsonb;
    v_raw text;
BEGIN
    IF p_product_id IS NULL OR p_date IS NULL OR p_product_id = ANY(p_stack) THEN
        RETURN QUERY SELECT 0::numeric, NULL::varchar;
        RETURN;
    END IF;

    SELECT pt.id, pt.replenishment_cost_type, pt.uom_id
      INTO v_tmpl, v_type, v_product_uom
      FROM product_product pp
      JOIN product_template pt ON pt.id = pp.product_tmpl_id
     WHERE pp.id = p_product_id;

    SELECT h.cost_new INTO v_cost
      FROM kai_replenishment_cost_history h
     WHERE h.product_id = p_product_id
       AND h.state = 'posted'
       AND h.date <= p_date
     ORDER BY h.date DESC, h.id DESC
     LIMIT 1;
    IF v_cost IS NOT NULL THEN
        RETURN QUERY SELECT v_cost, 'history_before'::varchar;
        RETURN;
    END IF;

    -- Hay lista de materiales aunque el tipo de costo no diga «LdM».
    SELECT b.id, b.product_qty, b.product_uom_id
      INTO v_bom_id, v_bom_qty, v_bom_uom
      FROM mrp_bom b
     WHERE b.product_tmpl_id = v_tmpl
       AND (b.product_id IS NULL OR b.product_id = p_product_id)
       AND (b.company_id IS NULL OR b.company_id = p_company_id OR b.company_id = p_main_company_id)
       AND COALESCE(b.active, TRUE)
       AND b.type = 'normal'
     ORDER BY (b.product_id IS NOT NULL) DESC, b.sequence, b.id
     LIMIT 1;
    v_has_bom := v_bom_id IS NOT NULL OR v_type = 'bom';

    -- Fabricado: la LdM a la fecha gana sobre un historial posterior.
    -- Una fila LdM posterior es un roll-up parcial y no se usa.
    IF v_has_bom AND v_bom_id IS NOT NULL AND p_depth < 8 THEN
            v_total := 0;
            FOR v_line IN
                SELECT bl.product_id, bl.product_qty, bl.product_uom_id,
                       comp_t.uom_id AS comp_uom_id
                  FROM mrp_bom_line bl
                  JOIN product_product comp ON comp.id = bl.product_id
                  JOIN product_template comp_t ON comp_t.id = comp.product_tmpl_id
                 WHERE bl.bom_id = v_bom_id
            LOOP
                SELECT c.cost INTO v_comp_cost
                  FROM kai_margin_unit_cost(
                      v_line.product_id, p_date, p_company_id, p_main_company_id,
                      p_depth + 1, p_stack || p_product_id
                  ) c;
                SELECT factor INTO v_from_factor FROM uom_uom WHERE id = v_line.product_uom_id;
                SELECT factor INTO v_to_factor FROM uom_uom WHERE id = v_line.comp_uom_id;
                v_qty := v_line.product_qty
                    * COALESCE(v_from_factor, 1)
                    / COALESCE(NULLIF(v_to_factor, 0), 1);
                v_total := v_total + COALESCE(v_comp_cost, 0) * COALESCE(v_qty, 0);
            END LOOP;
            IF COALESCE(v_bom_qty, 0) <> 0 THEN
                v_total := v_total / v_bom_qty;
                SELECT factor INTO v_from_factor FROM uom_uom WHERE id = v_bom_uom;
                SELECT factor INTO v_to_factor FROM uom_uom WHERE id = v_product_uom;
                v_total := v_total / COALESCE(NULLIF(v_from_factor, 0), 1) * COALESCE(v_to_factor, 1);
            END IF;
            IF COALESCE(v_total, 0) <> 0 THEN
                RETURN QUERY SELECT v_total, 'bom'::varchar;
                RETURN;
            END IF;
    END IF;

    -- El fabricado no usa historial posterior: una fila LdM de después es
    -- un roll-up parcial. En un comprado, el posterior vale solo si nació
    -- de una factura, no de una LdM.
    IF NOT v_has_bom THEN
        SELECT h.cost_new INTO v_cost
          FROM kai_replenishment_cost_history h
         WHERE h.product_id = p_product_id
           AND h.state = 'posted'
           AND h.origin = 'bill'
           AND h.date > p_date
         ORDER BY h.date ASC, h.id ASC
         LIMIT 1;
        IF v_cost IS NOT NULL THEN
            RETURN QUERY SELECT v_cost, 'history_after'::varchar;
            RETURN;
        END IF;
    END IF;

    SELECT si.price * (1 - COALESCE(si.discount, 0) / 100.0), si.currency_id
      INTO v_seller_price, v_seller_currency
      FROM product_supplierinfo si
     WHERE si.product_tmpl_id = v_tmpl
       AND si.company_id IS NULL
       AND si.price > 0
       AND (si.product_id IS NULL OR si.product_id = p_product_id)
     ORDER BY (si.product_id = p_product_id) DESC,
              si.last_date_price_updated DESC NULLS LAST,
              si.id DESC
     LIMIT 1;
    IF COALESCE(v_seller_price, 0) <> 0 THEN
        v_cost := v_seller_price;
        SELECT currency_id INTO v_main_currency FROM res_company WHERE id = p_main_company_id;
        IF v_seller_currency IS NOT NULL
           AND v_main_currency IS NOT NULL
           AND v_seller_currency <> v_main_currency THEN
            v_cost := kai_margin_convert_currency(
                v_cost, v_seller_currency, v_main_currency, p_company_id, p_date
            );
        END IF;
        RETURN QUERY SELECT v_cost, 'replenishment'::varchar;
        RETURN;
    END IF;

    v_cost := NULL;
    BEGIN
        SELECT pp.standard_price INTO v_standard
          FROM product_product pp
         WHERE pp.id = p_product_id;
        v_raw := NULLIF(v_standard ->> p_company_id::text, '');
        IF v_raw IS NULL THEN
            v_raw := NULLIF(v_standard ->> p_main_company_id::text, '');
        END IF;
        IF v_raw IS NOT NULL THEN
            v_cost := v_raw::numeric;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        v_cost := NULL;
    END;
    IF COALESCE(v_cost, 0) <> 0 THEN
        RETURN QUERY SELECT v_cost, 'standard'::varchar;
        RETURN;
    END IF;

    RETURN QUERY SELECT 0::numeric, NULL::varchar;
END;
$$ LANGUAGE plpgsql STABLE;
-- STATEMENT --
CREATE OR REPLACE FUNCTION kai_margin_convert_currency(
    p_amount numeric,
    p_from_currency integer,
    p_to_currency integer,
    p_company_id integer,
    p_date date
) RETURNS numeric AS $$
DECLARE
    v_from numeric;
    v_to numeric;
BEGIN
    IF p_amount IS NULL OR p_from_currency IS NULL OR p_to_currency IS NULL
       OR p_from_currency = p_to_currency THEN
        RETURN COALESCE(p_amount, 0);
    END IF;
    SELECT rate INTO v_from
      FROM res_currency_rate
     WHERE currency_id = p_from_currency
       AND (company_id IS NULL OR company_id = p_company_id)
       AND name <= p_date
     ORDER BY (company_id = p_company_id) DESC, name DESC
     LIMIT 1;
    SELECT rate INTO v_to
      FROM res_currency_rate
     WHERE currency_id = p_to_currency
       AND (company_id IS NULL OR company_id = p_company_id)
       AND name <= p_date
     ORDER BY (company_id = p_company_id) DESC, name DESC
     LIMIT 1;
    IF COALESCE(v_from, 0) = 0 THEN
        v_from := 1;
    END IF;
    RETURN p_amount * COALESCE(v_to, 1) / v_from;
END;
$$ LANGUAGE plpgsql STABLE;
"""

    def _out_refund_qty_sign_sql(self):
        """Signo de la cantidad estimada en una factura o nota de crédito.

        La nota de crédito resta solo si tiene una devolución de stock hecha
        (movimiento de retorno vinculado a la línea de venta). Un reembolso
        de precio, sin devolución, no mueve el CMV estimado.
        """
        move = self.env.get('stock.move')
        if (
            move is None
            or 'sale_line_id' not in move._fields
            or 'origin_returned_move_id' not in move._fields
        ):
            has_return = 'FALSE'
        else:
            has_return = """
                EXISTS (
                    SELECT 1
                    FROM sale_order_line_invoice_rel rel
                    JOIN stock_move return_move ON return_move.sale_line_id = rel.order_line_id
                    LEFT JOIN stock_picking return_picking ON return_picking.id = return_move.picking_id
                    WHERE rel.invoice_line_id = line.id
                      AND return_move.state = 'done'
                      AND (
                          return_move.origin_returned_move_id IS NOT NULL
                          OR return_picking.return_id IS NOT NULL
                      )
                )
            """
        return (
            "CASE WHEN move.move_type = 'out_refund' AND ("
            + has_return
            + ") THEN -1 WHEN move.move_type = 'out_refund' THEN 0 ELSE 1 END"
        )

    def _query(self):
        query = """
            WITH main_company AS (
                SELECT company.id AS id, company.currency_id AS currency_id
                FROM ir_model_data data
                JOIN res_company company ON company.id = data.res_id
                WHERE data.module = 'base'
                  AND data.name = 'main_company'
                  AND data.model = 'res.company'
                LIMIT 1
            )
            SELECT
                row_number() OVER (
                    ORDER BY src.company_id, src.product_id, src.month_date, src.cost_origin
                ) AS id,
                src.company_id AS company_id,
                company.currency_id AS currency_id,
                src.product_id AS product_id,
                product.product_tmpl_id AS product_tmpl_id,
                template.categ_id AS categ_id,
                src.month_date AS date,
                SUM(src.sales_amount) AS sales_amount,
                SUM(src.cogs_amount) AS cogs_amount,
                SUM(src.cogs_estimated) AS cogs_estimated,
                SUM(src.cogs_amount) + SUM(src.cogs_estimated) AS cogs_total,
                SUM(src.sales_amount) - SUM(src.cogs_amount) - SUM(src.cogs_estimated) AS margin_amount,
                CASE
                    WHEN ABS(SUM(src.sales_amount)) < 0.0000001 THEN 0
                    ELSE (SUM(src.sales_amount) - SUM(src.cogs_amount) - SUM(src.cogs_estimated))
                         / SUM(src.sales_amount) * 100
                END AS margin_percent,
                BOOL_OR(src.cost_origin IS NOT NULL) AS has_estimated_cogs,
                src.cost_origin AS cost_origin
            FROM (
                SELECT
                    move.company_id AS company_id,
                    line.product_id AS product_id,
                    date_trunc(
                        'month', COALESCE(move.invoice_date, move.date)
                    )::date AS month_date,
                    -line.balance AS sales_amount,
                    0::numeric AS cogs_amount,
                    CASE
                        WHEN NOT COALESCE(template.is_storable, FALSE)
                             OR (__KAI_QTY_SIGN__) = 0
                             OR EXISTS (
                                 SELECT 1
                                 FROM account_move_line cogs
                                 JOIN account_account cogs_account
                                   ON cogs_account.id = cogs.account_id
                                 WHERE cogs.move_id = move.id
                                   AND cogs.product_id = line.product_id
                                   AND cogs.display_type = 'cogs'
                                   AND cogs_account.account_type LIKE 'expense%'
                             )
                        THEN 0
                        ELSE
                            (__KAI_QTY_SIGN__)
                            * line.quantity
                            * COALESCE(line_uom.factor, 1)
                            / COALESCE(NULLIF(product_uom.factor, 0), 1)
                            * COALESCE((
                                SELECT CASE
                                    WHEN company.currency_id = main_company.currency_id THEN u.cost
                                    ELSE kai_margin_convert_currency(
                                        u.cost, main_company.currency_id, company.currency_id,
                                        move.company_id, COALESCE(move.invoice_date, move.date)
                                    )
                                END
                                FROM kai_margin_unit_cost(
                                    line.product_id,
                                    COALESCE(move.invoice_date, move.date),
                                    move.company_id,
                                    main_company.id
                                ) u
                                LIMIT 1
                            ), 0)
                    END AS cogs_estimated,
                    CASE
                        WHEN NOT COALESCE(template.is_storable, FALSE)
                             OR (__KAI_QTY_SIGN__) = 0
                             OR EXISTS (
                                 SELECT 1
                                 FROM account_move_line cogs
                                 JOIN account_account cogs_account
                                   ON cogs_account.id = cogs.account_id
                                 WHERE cogs.move_id = move.id
                                   AND cogs.product_id = line.product_id
                                   AND cogs.display_type = 'cogs'
                                   AND cogs_account.account_type LIKE 'expense%'
                             )
                        THEN NULL
                        ELSE (
                            SELECT u.origin
                            FROM kai_margin_unit_cost(
                                line.product_id,
                                COALESCE(move.invoice_date, move.date),
                                move.company_id,
                                main_company.id
                            ) u
                            LIMIT 1
                        )
                    END AS cost_origin
                FROM account_move_line line
                JOIN account_move move ON move.id = line.move_id
                JOIN account_account account ON account.id = line.account_id
                JOIN product_product product ON product.id = line.product_id
                JOIN product_template template ON template.id = product.product_tmpl_id
                JOIN res_company company ON company.id = move.company_id
                CROSS JOIN main_company
                LEFT JOIN uom_uom line_uom ON line_uom.id = line.product_uom_id
                LEFT JOIN uom_uom product_uom ON product_uom.id = template.uom_id
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
                    line.balance AS cogs_amount,
                    0::numeric AS cogs_estimated,
                    NULL::varchar AS cost_origin
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
                    END AS cogs_amount,
                    CASE
                        WHEN NOT COALESCE(template.is_storable, FALSE)
                             OR COALESCE(pos_line.total_cost, 0) <> 0
                        THEN 0
                        ELSE
                            (CASE WHEN pos_order.is_refund THEN -ABS(pos_line.qty) ELSE pos_line.qty END)
                            * COALESCE((
                                SELECT CASE
                                    WHEN company.currency_id = main_company.currency_id THEN u.cost
                                    ELSE kai_margin_convert_currency(
                                        u.cost, main_company.currency_id, company.currency_id,
                                        pos_order.company_id,
                                        (pos_order.date_order AT TIME ZONE 'UTC'
                                            AT TIME ZONE 'America/Argentina/Buenos_Aires')::date
                                    )
                                END
                                FROM kai_margin_unit_cost(
                                    pos_line.product_id,
                                    (pos_order.date_order AT TIME ZONE 'UTC'
                                        AT TIME ZONE 'America/Argentina/Buenos_Aires')::date,
                                    pos_order.company_id,
                                    main_company.id
                                ) u
                                LIMIT 1
                            ), 0)
                    END AS cogs_estimated,
                    CASE
                        WHEN NOT COALESCE(template.is_storable, FALSE)
                             OR COALESCE(pos_line.total_cost, 0) <> 0
                        THEN NULL
                        ELSE (
                            SELECT u.origin
                            FROM kai_margin_unit_cost(
                                pos_line.product_id,
                                (pos_order.date_order AT TIME ZONE 'UTC'
                                    AT TIME ZONE 'America/Argentina/Buenos_Aires')::date,
                                pos_order.company_id,
                                main_company.id
                            ) u
                            LIMIT 1
                        )
                    END AS cost_origin
                FROM pos_order_line pos_line
                JOIN pos_order ON pos_order.id = pos_line.order_id
                JOIN product_product product ON product.id = pos_line.product_id
                JOIN product_template template ON template.id = product.product_tmpl_id
                JOIN res_company company ON company.id = pos_order.company_id
                CROSS JOIN main_company
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
                src.month_date,
                src.cost_origin
        """
        return query.replace('__KAI_QTY_SIGN__', self._out_refund_qty_sign_sql())
