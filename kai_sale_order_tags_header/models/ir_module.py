from odoo import api, models
from odoo.exceptions import UserError
from odoo.modules.module import get_manifest
from odoo.tools.translate import _

# Names published by this module before 19.0.1.4.3. A database language keeps
# the previous value because shortdesc and summary are translated fields and
# the core upgrade writes only the source language.
_LEGACY_SHORTDESC = frozenset({
    'Sale Order: tags in header',
})
_LEGACY_SUMMARY = frozenset({
    'Show sale order tags (Etiquetas) in the form header and next to the number '
    'on the printed PDF, plus contact / secondary contact / delivery phones on '
    'the PDF. Show the delivery date (commitment_date) next to the order date, '
    'and print that date and time on the quotation, order and proforma PDF. '
    'Repeat a compact customer / order / dates / tags header on every PDF page, '
    'with a sale-only paper format so the block sits under the logo.',
})


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    @api.model
    def _kai_upgrade_optional_adapters(self):
        """Run from this module's data files, so only on install or upgrade.

        Registry startup must not write. Views and report assignments that
        depend on optional modules are applied here, once, by the module
        lifecycle. A second upgrade writes a row only when the value differs.
        """
        self._kai_sync_manifest_metadata()
        self._kai_assign_optional_paperformats()
        self._kai_mark_l10n_ar_adapter()

    @api.model
    def _kai_sync_manifest_metadata(self):
        manifest = get_manifest('kai_sale_order_tags_header') or {}
        module = self.search([('name', '=', 'kai_sale_order_tags_header')], limit=1)
        if not module:
            return
        self._kai_align_translated_field(
            module, 'shortdesc', manifest.get('name') or '', _LEGACY_SHORTDESC,
        )
        self._kai_align_translated_field(
            module, 'summary', manifest.get('summary') or '', _LEGACY_SUMMARY,
        )

    @api.model
    def _kai_align_translated_field(self, module, field_name, new_value, legacy):
        if not new_value:
            return
        stored = module._fields[field_name]._get_stored_translations(module) or {}
        source = stored.get('en_US') or ''
        langs = [code for code, _name in self.env['res.lang'].get_installed()]
        if 'en_US' not in langs:
            langs.append('en_US')
        for lang in langs:
            current = stored.get(lang)
            if current == new_value:
                continue
            # A translation that is neither the English source nor a previous
            # manifest string was edited on purpose. Leave that language alone.
            if current and current != source and current not in legacy:
                continue
            module.with_context(lang=lang).write({field_name: new_value})
            stored[lang] = new_value
            if lang == 'en_US':
                source = new_value

    @api.model
    def _kai_assign_optional_paperformats(self):
        """Raw quotation report, only when that module is installed.

        Purchase reports are assigned from this module's XML because purchase
        is a hard dependency. Invoice actions are not assigned: they also
        print vendor bills.
        """
        paperformat = self.env.ref(
            'kai_sale_order_tags_header.paperformat_saleorder',
            raise_if_not_found=False,
        )
        raw = self.env.ref(
            'sale_pdf_quote_builder.action_report_saleorder_raw',
            raise_if_not_found=False,
        )
        if paperformat and raw and raw.paperformat_id != paperformat:
            raw.paperformat_id = paperformat

    @api.model
    def _kai_mark_l10n_ar_adapter(self):
        l10n_ar = self.search([('name', '=', 'l10n_ar')], limit=1)
        if l10n_ar.state != 'installed':
            return
        glue = self.search([('name', '=', 'kai_sale_order_tags_header_l10n_ar')], limit=1)
        if not glue:
            raise UserError(_(
                'Argentine invoices need the module kai_sale_order_tags_header_l10n_ar '
                'on the addons path. It is not installed as a hard dependency.'
            ))
        # Mark only this adapter. button_upgrade() also refreshes the whole
        # Apps list and would rewrite other modules.
        if glue.state == 'uninstalled':
            glue.button_install()
        elif glue.state == 'installed':
            glue.write({'state': 'to upgrade'})
