# Copyright 2026 Kaizendo
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


def _kai_iter_afip_errs(raw):
    """Normalize AFIP/pyafipws Errors payloads into (code, msg) pairs."""
    if not raw:
        return
    if isinstance(raw, dict) and "Err" in raw:
        raw = raw["Err"]
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return
    for item in raw:
        if not isinstance(item, dict):
            continue
        err = item.get("Err", item)
        if isinstance(err, list):
            for sub in err:
                if isinstance(sub, dict):
                    yield sub.get("Code"), sub.get("Msg")
            continue
        if isinstance(err, dict):
            yield err.get("Code"), err.get("Msg")


class AccountMove(models.Model):
    _inherit = "account.move"

    kai_l10n_ar_afip_currency_code = fields.Char(
        related="currency_id.l10n_ar_afip_code",
        string="AFIP currency code",
    )

    def _kai_is_ars_afip_currency(self):
        self.ensure_one()
        currency = self.currency_id
        company_currency = self.company_id.currency_id
        afip_code = currency.l10n_ar_afip_code or ""
        return afip_code == "PES" or currency == company_currency

    def _kai_format_afip_errors(self, ret, result):
        messages = []
        sources = []
        if isinstance(result, dict):
            sources.append(result.get("Errors"))
        if isinstance(ret, dict):
            sources.append(ret.get("Errors"))
        for raw in sources:
            for code, msg in _kai_iter_afip_errs(raw):
                text = " ".join(
                    str(part) for part in (code, msg) if part not in (None, "")
                ).strip()
                if text and text not in messages:
                    messages.append(text)
        return "\n".join(messages)

    def pyafipws_get_currency_rate(self, ws):
        """Call FEParamGetCotizacion without assuming ResultGet is present.

        Upstream pyafipws.ParamGetCotizacion does
        ret["FEParamGetCotizacionResult"]["ResultGet"] and raises KeyError
        when AFIP returns only Errors (typical for MonId=PES, or when there
        is no quotation for that currency/date).
        """
        self.ensure_one()
        moneda_id = self.currency_id.l10n_ar_afip_code
        if not moneda_id:
            raise UserError(
                _("The currency %s has no AFIP code (l10n_ar_afip_code).")
                % self.currency_id.display_name
            )
        fecha = self.invoice_date.strftime("%Y%m%d") if self.invoice_date else None
        try:
            ret = ws.client.FEParamGetCotizacion(
                Auth={"Token": ws.Token, "Sign": ws.Sign, "Cuit": ws.Cuit},
                MonId=moneda_id,
                FchCotiz=fecha,
            )
        except Exception as err:
            raise UserError(
                _("Could not get the AFIP currency quotation: %s") % err
            ) from err

        result = {}
        if isinstance(ret, dict):
            result = ret.get("FEParamGetCotizacionResult") or {}
        err_text = self._kai_format_afip_errors(ret, result)
        res = result.get("ResultGet") if isinstance(result, dict) else None
        if not res:
            raise UserError(
                _(
                    "AFIP did not return a quotation for currency %(currency)s "
                    "(MonId=%(mon)s).%(err)s"
                )
                % {
                    "currency": self.currency_id.display_name,
                    "mon": moneda_id,
                    "err": ("\n%s" % err_text) if err_text else "",
                }
            )
        mon_cotiz = res.get("MonCotiz") if isinstance(res, dict) else None
        if mon_cotiz in (None, ""):
            raise UserError(
                _(
                    "AFIP did not return a valid MonCotiz for currency %(currency)s "
                    "(MonId=%(mon)s).%(err)s"
                )
                % {
                    "currency": self.currency_id.display_name,
                    "mon": moneda_id,
                    "err": ("\n%s" % err_text) if err_text else "",
                }
            )
        try:
            if float(mon_cotiz) == 0:
                raise ValueError("zero")
        except (TypeError, ValueError) as err:
            raise UserError(
                _(
                    "AFIP did not return a valid MonCotiz for currency %(currency)s "
                    "(MonId=%(mon)s): %(value)s"
                )
                % {
                    "currency": self.currency_id.display_name,
                    "mon": moneda_id,
                    "value": mon_cotiz,
                }
            ) from err
        return str(mon_cotiz)

    def get_pyafipws_currency_rate(self):
        self.ensure_one()
        if self._kai_is_ars_afip_currency():
            if not self.invoice_currency_rate or self.invoice_currency_rate != 1.0:
                self.invoice_currency_rate = 1.0
            body = _(
                "AFIP currency rate: 1. AFIP does not quote ARS (PES); the rate is 1."
            )
            self.message_post(body=body)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("AFIP currency rate"),
                    "message": _(
                        "The invoice currency is %s. AFIP does not provide a "
                        "quotation for ARS (PES); the rate remains 1."
                    )
                    % self.currency_id.display_name,
                    "type": "info",
                    "sticky": False,
                },
            }

        afip_ws = self.journal_id.afip_ws
        if not afip_ws:
            raise UserError(_("The journal has no AFIP web service configured."))
        ws = self.company_id.get_connection(afip_ws).connect()
        afipws_get_currency_rate = self.pyafipws_get_currency_rate(ws)
        try:
            rate_float = float(afipws_get_currency_rate)
        except (TypeError, ValueError) as err:
            raise UserError(
                _("AFIP did not return a valid quotation: %s")
                % afipws_get_currency_rate
            ) from err
        if not rate_float:
            raise UserError(
                _("AFIP did not return a valid quotation: %s")
                % afipws_get_currency_rate
            )
        # Do not write any rate until the value is validated above.
        self.invoice_currency_rate = 1 / rate_float
        self.message_post(
            body=_("AFIP currency rate: %s") % afipws_get_currency_rate
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("AFIP currency rate"),
                "message": _("AFIP currency rate: %s") % afipws_get_currency_rate,
                "type": "success",
                "sticky": False,
            },
        }
