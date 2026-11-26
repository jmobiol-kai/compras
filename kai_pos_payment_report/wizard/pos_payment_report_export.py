# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import base64
import calendar
import io
import unicodedata
from collections import defaultdict
from datetime import datetime, time, timedelta

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from odoo import api, fields, models
from odoo.exceptions import UserError

# Dark teal for year, most PdV headers and totals; blue block for "Tarde".
COLOR_TEAL = "#0E5C63"
COLOR_TEAL_SUB = "#147A82"
COLOR_BLUE = "#215E8C"
COLOR_BLUE_SUB = "#2E75B6"
COLOR_WHITE = "#FFFFFF"
COLOR_BORDER = "#1F1F1F"

SUBHEADERS = (
    "EFECTIVO",
    "MEDIOS ELECTRÓNICOS",
    "VENTAS FE",
    "VENTAS X",
)


def _strip_accents(value):
    text = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn")


class KaiPosPaymentReportExport(models.TransientModel):
    _name = "kai.pos.payment.report.export"
    _description = "Export POS payments spreadsheet"

    date_from = fields.Date(
        string="From",
        required=True,
        default=lambda self: self._default_date_from(),
    )
    date_to = fields.Date(
        string="To",
        required=True,
        default=lambda self: self._default_date_to(),
    )

    @api.model
    def _default_date_from(self):
        today = fields.Date.context_today(self)
        return today.replace(day=1)

    @api.model
    def _default_date_to(self):
        today = fields.Date.context_today(self)
        last = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=last)

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise UserError(self.env._("The start date must be on or before the end date."))

    def action_export_xlsx(self):
        self.ensure_one()
        content, filename = self._generate_xlsx()
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "datas": base64.b64encode(content),
            "res_model": self._name,
            "res_id": self.id,
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    def _report_configs(self):
        """Active POS configs, ordered by sequence if present, then known names."""
        configs = self.env["pos.config"].search([("active", "=", True)])
        return configs.sorted(key=self._config_sort_key)

    def _config_sort_key(self, config):
        sequence = getattr(config, "sequence", None)
        if sequence is None:
            sequence = 10
        return (sequence, self._config_name_rank(config.name), (config.name or "").casefold())

    def _config_name_rank(self, name):
        key = _strip_accents(name or "").upper()
        if "MANANA" in key:
            return 1
        if "TARDE" in key:
            return 2
        if "BUFFET" in key or "BUFET" in key:
            return 3
        return 10

    def _config_title(self, config):
        raw = config.name or ""
        key = _strip_accents(raw).upper()
        if "MANANA" in key:
            return "CAFETERÍA MAÑANA"
        if "TARDE" in key:
            return "CAFETERÍA TARDE"
        if "BUFFET" in key or "BUFET" in key:
            return "BUFFET"
        return raw.upper()

    def _is_tarde(self, config):
        return "TARDE" in _strip_accents(config.name or "").upper()

    def _build_matrix(self):
        """Return (configs, days, totals) for the selected period.

        `totals[config][day] = {cash, electronic, invoiced, not_invoiced}`.
        Days with no sales are still present with zeros.
        """
        self.ensure_one()
        configs = self._report_configs()
        days = []
        day = self.date_from
        while day <= self.date_to:
            days.append(day)
            day += timedelta(days=1)

        zeros = lambda: {"cash": 0.0, "electronic": 0.0, "invoiced": 0.0, "not_invoiced": 0.0}
        totals = {config.id: defaultdict(zeros) for config in configs}

        payments = self.env["pos.payment"].search([
            ("payment_date_date", ">=", self.date_from),
            ("payment_date_date", "<=", self.date_to),
            ("pos_order_id.state", "!=", "cancel"),
            ("config_id", "in", configs.ids),
        ])
        for payment in payments:
            config = payment.config_id
            if not config or config.id not in totals:
                continue
            day = payment.payment_date_date
            bucket = totals[config.id][day]
            amount = payment.amount or 0.0
            if payment.payment_medium_type == "efectivo":
                bucket["cash"] += amount
            else:
                bucket["electronic"] += amount
            fe_journal = config.invoice_journal_id
            if fe_journal and payment.sales_journal_id == fe_journal:
                bucket["invoiced"] += amount
            else:
                # Ventas X (default_journalx) and any other non-FE leftover,
                # so cash + electronic = invoiced + not_invoiced.
                bucket["not_invoiced"] += amount
        return configs, days, totals

    def _generate_xlsx(self):
        self.ensure_one()
        configs, days, totals = self._build_matrix()
        if not configs:
            raise UserError(self.env._("There is no active point of sale to export."))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True, "remove_timezone": True})
        sheet = workbook.add_worksheet("Pagos PdV")

        border = {"border": 1, "border_color": COLOR_BORDER}
        fmt_year = workbook.add_format({
            **border,
            "bold": True,
            "font_size": 16,
            "font_color": COLOR_WHITE,
            "bg_color": COLOR_TEAL,
            "align": "center",
            "valign": "vcenter",
        })

        def header_format(bg, size=11):
            return workbook.add_format({
                **border,
                "bold": True,
                "font_size": size,
                "font_color": COLOR_WHITE,
                "bg_color": bg,
                "align": "center",
                "valign": "vcenter",
                "text_wrap": True,
            })

        fmt_head_teal = header_format(COLOR_TEAL, 12)
        fmt_sub_teal = header_format(COLOR_TEAL_SUB, 9)
        fmt_head_blue = header_format(COLOR_BLUE, 12)
        fmt_sub_blue = header_format(COLOR_BLUE_SUB, 9)
        fmt_date = workbook.add_format({
            **border,
            "num_format": "d/m/yy",
            "align": "center",
            "valign": "vcenter",
        })
        fmt_num = workbook.add_format({
            **border,
            "num_format": "#,##0.00",
            "align": "right",
        })
        fmt_total_label = workbook.add_format({
            **border,
            "bold": True,
            "font_color": COLOR_WHITE,
            "bg_color": COLOR_TEAL,
            "align": "center",
            "valign": "vcenter",
        })
        fmt_total_num = workbook.add_format({
            **border,
            "bold": True,
            "num_format": "#,##0.00",
            "font_color": COLOR_WHITE,
            "bg_color": COLOR_TEAL,
            "align": "right",
        })

        year = self.date_from.year if self.date_from.year == self.date_to.year else "%s-%s" % (
            self.date_from.year, self.date_to.year
        )
        sheet.merge_range(0, 0, 1, 0, year, fmt_year)
        sheet.set_column(0, 0, 11)
        sheet.set_row(0, 22)
        sheet.set_row(1, 28)

        keys = ("cash", "electronic", "invoiced", "not_invoiced")
        col = 1
        config_columns = {}
        for config in configs:
            title = self._config_title(config)
            tarde = self._is_tarde(config)
            sheet.merge_range(0, col, 0, col + 3, title, fmt_head_blue if tarde else fmt_head_teal)
            sub_fmt = fmt_sub_blue if tarde else fmt_sub_teal
            for offset, label in enumerate(SUBHEADERS):
                sheet.write(1, col + offset, label, sub_fmt)
                sheet.set_column(col + offset, col + offset, 16)
            config_columns[config.id] = col
            col += 4

        last_col = col - 1
        last_data_row = 1 + len(days)  # 0-index: first data row = 2, last = 1+len(days)
        grand = {config.id: {k: 0.0 for k in keys} for config in configs}

        for index, day in enumerate(days):
            row = 2 + index
            sheet.write_datetime(row, 0, datetime.combine(day, time()), fmt_date)
            for config in configs:
                values = totals[config.id][day]
                start_col = config_columns[config.id]
                for offset, key in enumerate(keys):
                    amount = values[key]
                    grand[config.id][key] += amount
                    sheet.write_number(row, start_col + offset, amount, fmt_num)

        total_row = 2 + len(days)
        sheet.write(total_row, 0, "TOTAL", fmt_total_label)
        first_data_row = 3  # 1-based Excel
        excel_last_data = 2 + len(days)
        for config in configs:
            start_col = config_columns[config.id]
            for offset, key in enumerate(keys):
                letter = xl_col_to_name(start_col + offset)
                formula = "=SUM(%s%s:%s%s)" % (letter, first_data_row, letter, excel_last_data)
                sheet.write_formula(
                    total_row, start_col + offset, formula, fmt_total_num, grand[config.id][key]
                )

        sheet.freeze_panes(2, 1)
        sheet.autofilter(1, 0, total_row, last_col)
        sheet.fit_to_pages(1, 0)
        sheet.set_landscape()
        sheet.set_paper(9)  # A4
        sheet.repeat_rows(0, 1)
        workbook.close()
        filename = "planilla_pagos_pdv_%s_%s.xlsx" % (
            self.date_from.isoformat(),
            self.date_to.isoformat(),
        )
        return output.getvalue(), filename
