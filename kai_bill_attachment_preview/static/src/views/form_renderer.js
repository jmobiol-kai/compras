/** @odoo-module **/
/*
 * Restore the mail attachment side preview (COMBO layout) on invoices and
 * vendor bills when another addon disables FormRenderer.hasFile().
 *
 * OCA web_responsive (19.0) patches FormRenderer.prototype.hasFile() to
 * always return false. mail's mailLayout() then never returns "COMBO", so the
 * <div class="o_attachment_preview"/> of account.view_move_form is never
 * rendered and the chatter stays on the side.
 *
 * We do not touch hasFile() (patch order against web_responsive is not
 * guaranteed and other models keep web_responsive's behaviour). Instead we
 * wrap mail's mailLayout(), which web_responsive does not patch, and compute
 * the "has file" condition ourselves for account.move only.
 */
import "@mail/chatter/web/form_renderer";

import { SIZES } from "@web/core/ui/ui_service";
import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";

const PREVIEW_MODELS = ["account.move"];

patch(FormRenderer.prototype, {
    /**
     * Same check as mail's FormRenderer.hasFile(), immune to overrides.
     * @returns {boolean}
     */
    _kaiHasPreviewFile() {
        if (!this.mailStore || !this.props.record.resId) {
            return false;
        }
        this.messagingState.thread = this.mailStore.Thread.insert({
            id: this.props.record.resId,
            model: this.props.record.resModel,
        });
        return this.messagingState.thread.attachmentsInWebClientView.length > 0;
    },

    mailLayout(hasAttachmentContainer) {
        const layout = super.mailLayout(hasAttachmentContainer);
        if (
            !hasAttachmentContainer ||
            !PREVIEW_MODELS.includes(this.props.record.resModel) ||
            !["SIDE_CHATTER", "BOTTOM_CHATTER"].includes(layout)
        ) {
            return layout;
        }
        if (!this._kaiHasPreviewFile()) {
            return layout;
        }
        const xxl = this.uiService.size >= SIZES.XXL;
        if (this.mailPopoutService?.externalWindow) {
            return xxl ? "EXTERNAL_COMBO_XXL" : "EXTERNAL_COMBO";
        }
        return xxl ? "COMBO" : layout;
    },
});
