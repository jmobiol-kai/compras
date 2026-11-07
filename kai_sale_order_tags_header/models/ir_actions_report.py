import logging
import os
import re
import subprocess
import tempfile
from collections import OrderedDict

import lxml.html
from lxml import etree

from odoo import models
from odoo.addons.base.models.ir_actions_report import _wkhtml
from odoo.tools.pdf import PdfFileReader

_logger = logging.getLogger(__name__)

# Quotation, raw quote (no hard dependency on sale_pdf_quote_builder) and proforma.
SALE_REPORT_NAMES = (
    'sale.report_saleorder',
    'sale.report_saleorder_raw',
    'sale.report_saleorder_pro_forma',
)
# RFQ and confirmed purchase order. Vendor bills are not in this list.
PURCHASE_REPORT_NAMES = (
    'purchase.report_purchaseorder',
    'purchase.report_purchasequotation',
)
# Customer invoices and credit notes share these actions with vendor bills.
# The paper format stays the company one; only a rendered customer header
# replaces the top margin.
INVOICE_REPORT_NAMES = (
    'account.report_invoice',
    'account.report_invoice_with_payments',
)
_KAI_SPLIT_REPORTS = SALE_REPORT_NAMES + PURCHASE_REPORT_NAMES + INVOICE_REPORT_NAMES

# Painted header bottom + this gap is where the table starts.
# PIN_MM keeps wkhtmltopdf from sliding that block down into the table:
# header_spacing stays this far under margin_top.
_GAP_MM = 10.0
_PIN_MM = 8.0
_NUMBER = r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?'


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def get_paperformat(self):
        # Invoices are not listed: the same actions also print vendor bills,
        # which must keep the company paper format.
        if len(self) == 1 and self.report_name in SALE_REPORT_NAMES + PURCHASE_REPORT_NAMES:
            paperformat = self.env.ref(
                'kai_sale_order_tags_header.paperformat_saleorder',
                raise_if_not_found=False,
            )
            if paperformat:
                return paperformat
        return super().get_paperformat()

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        """One wkhtmltopdf run per sale order.

        A single run uses one top margin for every document in the batch, so a
        long header would push a short order down with it. Separate runs keep
        each measured margin, and the caller still merges the PDFs in order.
        """
        res_ids = list(res_ids or [])
        report = self._get_report(report_ref) if report_ref else self.browse()
        if (
            report
            and report.report_name in _KAI_SPLIT_REPORTS
            and len(res_ids) > 1
            and len(set(res_ids)) == len(res_ids)
        ):
            collected = OrderedDict()
            for res_id in res_ids:
                part = super()._render_qweb_pdf_prepare_streams(
                    report_ref, dict(data or {}), res_ids=[res_id],
                )
                if part and res_id in part:
                    collected[res_id] = part[res_id]
                elif part:
                    collected[res_id] = next(iter(part.values()))
            return collected
        return super()._render_qweb_pdf_prepare_streams(
            report_ref, data, res_ids=res_ids,
        )

    def _run_wkhtmltopdf(
        self, bodies, report_ref=False, header=None, footer=None,
        landscape=False, specific_paperformat_args=None, set_viewport_size=False,
    ):
        if header and report_ref and _wkhtml().is_patched_qt:
            report = self._get_report(report_ref)
            if report.report_name in _KAI_SPLIT_REPORTS:
                measured = self._kai_measured_paper_args(header, report.get_paperformat())
                if measured:
                    specific_paperformat_args = dict(specific_paperformat_args or {})
                    specific_paperformat_args.update(measured)
        return super()._run_wkhtmltopdf(
            bodies,
            report_ref=report_ref,
            header=header,
            footer=footer,
            landscape=landscape,
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=set_viewport_size,
        )

    def _kai_measured_paper_args(self, header_html, paperformat):
        """Margin for this header only. None keeps the paper format fallback.

        wkhtmltopdf cannot see a header's height when --margin-top is set, and
        one value then applies to every page. Rendering that same header HTML
        as its own page and reading the lowest painted edge gives the height
        actually used in the PDF. No extra JavaScript.
        """
        if isinstance(header_html, bytes):
            header_html = header_html.decode()
        try:
            measure_html = self._kai_header_measure_html(header_html)
        except (ValueError, etree.ParserError, etree.XMLSyntaxError):
            return None
        if not measure_html:
            return None
        height = self._kai_header_height_mm(measure_html, paperformat)
        if not height or height < 8 or height > 150:
            return None
        margin_top = height + _GAP_MM
        return {
            'data-report-margin-top': f'{margin_top:.2f}',
            'data-report-header-spacing': f'{max(margin_top - _PIN_MM, 0):.2f}',
        }

    def _kai_header_measure_html(self, header_html):
        """Original header document when it contains one repeating block.

        The HTML is returned unchanged. Re-serializing it collapses the title
        width and the measured height comes out too large. Vendor bills do
        not carry ``kai_sale_repeat``, so this returns nothing and the
        company paper format is left alone. Argentina original/duplicate in
        one file is more than one header; that case also keeps the company
        format, which does not cover the lines.
        """
        root = lxml.html.fromstring(header_html)
        nodes = root.xpath(
            "//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')"
            " and .//*[@name='kai_sale_repeat']]"
        )
        # One header: measure the original document. Re-serializing it with
        # lxml collapses the title width and the height comes out too large.
        # Several headers means Argentina original/duplicate in one file; the
        # company paper format stays, which does not overlap the lines.
        if len(nodes) != 1:
            return None
        return header_html

    def _kai_header_height_mm(self, header_html, paperformat):
        info = _wkhtml()
        if not info.bin or info.state != 'ok':
            return None
        delay = self.env['ir.config_parameter'].sudo().get_param('report.print_delay', '1000')
        dpi = int(paperformat.dpi or 96)
        html_path = pdf_path = None
        try:
            html_fd, html_path = tempfile.mkstemp(suffix='.html', prefix='kai_sale_header_')
            os.close(html_fd)
            pdf_fd, pdf_path = tempfile.mkstemp(suffix='.pdf', prefix='kai_sale_header_')
            os.close(pdf_fd)
            with open(html_path, 'wb') as handle:
                handle.write(header_html.encode())
            command = [
                info.bin, '--quiet', '--disable-local-file-access',
                '--page-size', paperformat.format or 'A4',
                '--margin-top', '0', '--margin-bottom', '0',
                '--margin-left', '0', '--margin-right', '0',
                '--dpi', str(dpi),
                '--javascript-delay', str(delay or '0'),
            ]
            if info.dpi_zoom_ratio:
                command.extend(['--zoom', str(96.0 / dpi)])
            command.extend([html_path, pdf_path])
            completed = subprocess.run(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=60, check=False,
            )
            # Exit 1 is wkhtmltopdf's network warning (about:blank). The PDF
            # is still usable; Odoo keeps those files too.
            if completed.returncode not in (0, 1) or os.path.getsize(pdf_path) < 500:
                _logger.warning('Sale header measurement failed (wkhtmltopdf %s).', completed.returncode)
                return None
            with open(pdf_path, 'rb') as handle:
                return _painted_bottom_mm(handle.read())
        except (OSError, subprocess.TimeoutExpired, ValueError):
            _logger.warning('Sale header measurement failed; using the sale paper format margins.')
            return None
        finally:
            for path in (html_path, pdf_path):
                if not path:
                    continue
                try:
                    os.remove(path)
                except OSError:
                    pass


def _painted_bottom_mm(pdf_bytes):
    """Lowest painted rectangle on a wkhtmltopdf page, in millimetres from the top.

    The logo block and the rule under the dates are rectangles. Text matrices
    are skipped: after wkhtmltopdf flips the page they no longer sit on the
    content and would mark the whole sheet as painted.
    """
    reader = PdfFileReader(io_bytes(pdf_bytes), strict=False)
    page = reader.pages[0] if hasattr(reader, 'pages') else reader.getPage(0)
    box = page.mediabox if hasattr(page, 'mediabox') else page.mediaBox
    page_height = float(box[3]) - float(box[1])
    data = _page_content(page)
    if not data:
        return None
    text = data.decode('latin1', errors='replace')
    ctm = (1, 0, 0, 1, 0, 0)
    saved = []
    numbers = []
    lowest = page_height
    pattern = re.compile(rf'({_NUMBER})|(q|Q|cm|re|Tm|Td)\b')
    for match in pattern.finditer(text):
        if match.group(1):
            numbers.append(float(match.group(1)))
            continue
        operator = match.group(2)
        if operator == 'q':
            saved.append(ctm)
        elif operator == 'Q':
            if saved:
                ctm = saved.pop()
        elif operator == 'cm' and len(numbers) >= 6:
            ctm = _multiply(ctm, tuple(numbers[-6:]))
        elif operator == 're' and len(numbers) >= 4:
            # Filled rectangles: logo box and the rule under the dates.
            # Text matrices are not absolute once wkhtmltopdf flips the page,
            # and counting them marks the whole page as painted.
            x, y, width, height = numbers[-4:]
            if height > 0.2 or width > 0.2:
                for px, py in ((x, y), (x + width, y), (x, y + height), (x + width, y + height)):
                    lowest = min(lowest, _apply(ctm, px, py)[1])
        numbers.clear()
    if lowest >= page_height:
        return None
    return (page_height - lowest) / 72.0 * 25.4


def io_bytes(payload):
    import io
    return io.BytesIO(payload)


def _multiply(left, right):
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1,
    )


def _apply(matrix, x, y):
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _page_content(page):
    contents = page.get_contents() if hasattr(page, 'get_contents') else page.getContents()
    if contents is None:
        return b''
    streams = contents if isinstance(contents, (list, tuple)) else None
    if streams is None and not hasattr(contents, 'get_data') and not hasattr(contents, 'getData'):
        streams = list(contents)
    if streams is None:
        streams = [contents]
    parts = []
    for stream in streams:
        if hasattr(stream, 'get_data'):
            parts.append(stream.get_data())
        else:
            parts.append(stream.getData())
    return b'\n'.join(parts)
