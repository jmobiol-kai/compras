/** @odoo-module **/
// OCA account_reconcile_oca leaves manual_* empty until a reconcile line is
// clicked: selectReconcileLine writes manual_reference, and the onchange
// copies account, partner, name and amount onto the Manual operation page.
// The pending counterpart is the gray line with kind "suspense" (the journal
// suspense account, "Cuenta transitoria"). Enterprise 16 opened that line by
// itself. Do the same when a bank statement line is shown.

import {onWillUnmount, useEffect} from "@odoo/owl";
import {patch} from "@web/core/utils/patch";
import {AccountReconcileDataWidget} from "@account_reconcile_oca/components/account_reconcile_oca_data/account_reconcile_oca_data.esm";

patch(AccountReconcileDataWidget.prototype, {
    setup() {
        super.setup(...arguments);
        this.kaiAlive = true;
        // `${resId}:open` once we have auto-selected for this visit, or
        // `${resId}:reconciled` while the line is reconciled so the next
        // unreconcile selects the new suspense counterpart again.
        this.kaiLastAutoSelectKey = null;
        onWillUnmount(() => {
            this.kaiAlive = false;
        });
        useEffect(
            () => {
                this.kaiSelectPendingSuspenseLine();
            },
            () => [
                this.props.record.resId,
                this.props.record.data && this.props.record.data.is_reconciled,
                this.kaiPendingSuspenseLine()?.reference || false,
            ]
        );
    },

    /**
     * Pending open-balance counterpart.
     * Null for other models (account reconcile shares this widget but its
     * onchange does not fill manual_*), reconciled lines, or when the user
     * already has a line selected.
     */
    kaiPendingSuspenseLine() {
        const record = this.props.record;
        if (!record || record.resModel !== "account.bank.statement.line") {
            return null;
        }
        if (record.data.is_reconciled || record.data.manual_reference) {
            return null;
        }
        const info = record.data[this.props.name];
        const lines = info && info.data;
        if (!lines || !lines.length) {
            return null;
        }
        return lines.find((line) => line.kind === "suspense" && line.reference) || null;
    },

    kaiSelectPendingSuspenseLine() {
        const record = this.props.record;
        if (!record || !this.kaiAlive || record.resModel !== "account.bank.statement.line") {
            return;
        }
        const cycleKey = record.data.is_reconciled
            ? `${record.resId}:reconciled`
            : `${record.resId}:open`;
        if (record.data.is_reconciled) {
            this.kaiLastAutoSelectKey = cycleKey;
            return;
        }
        if (this.kaiLastAutoSelectKey === cycleKey) {
            return;
        }
        const line = this.kaiPendingSuspenseLine();
        if (!line) {
            return;
        }
        this.kaiLastAutoSelectKey = cycleKey;
        this.kaiApplySuspenseLine(line);
    },

    /**
     * Same write as a click on the gray line. The notebook renders only the
     * active page, so Manual operation is opened after the onchange has put
     * manual_account_id, manual_partner_id, manual_name and manual_amount on
     * the record. A click that lands in the meantime keeps its own line.
     */
    async kaiApplySuspenseLine(line) {
        const record = this.props.record;
        const resId = record.resId;
        await record.update({manual_reference: line.reference});
        if (
            !this.kaiAlive ||
            record.resId !== resId ||
            record.data.manual_reference !== line.reference
        ) {
            return;
        }
        this.kaiOpenManualOperation();
    },

    kaiOpenManualOperation() {
        if (!this.env.bus) {
            return;
        }
        // Same payload as AccountReconcileDataWidget.selectReconcileLine.
        // ReconcileFormNotebook reads ev.detail.detail and calls
        // originalEv.preventDefault().
        const originalEv = {preventDefault() {}};
        const triggerEv = new CustomEvent("reconcile-page-navigate", {
            detail: {name: "manual", originalEv},
        });
        this.env.bus.trigger("RECONCILE_PAGE_NAVIGATE", triggerEv);
    },
});
