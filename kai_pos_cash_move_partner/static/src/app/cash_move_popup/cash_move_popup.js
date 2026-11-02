/** @odoo-module */

import { CashMovePopup } from "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup";
import { SelectMenu } from "@web/core/select_menu/select_menu";
import { patch } from "@web/core/utils/patch";
import { onWillUnmount } from "@odoo/owl";

patch(CashMovePopup, {
    components: {
        ...CashMovePopup.components,
        SelectMenu,
    },
});

patch(CashMovePopup.prototype, {
    setup() {
        super.setup(...arguments);
        this._alive = true;
        this._moveRequest = 0;
        this._partnerRequest = 0;
        Object.assign(this.state, {
            partnerId: false,
            partnerName: "",
            partnerChoices: [],
            moves: [],
            selectedMoveIds: [],
            journals: [],
            destJournalId: false,
            loadingMoves: false,
        });
        onWillUnmount(() => {
            this._alive = false;
        });
        this.loadDestJournals();
    },

    onClickButton(type) {
        super.onClickButton(type);
        this.state.selectedMoveIds = [];
        this.loadOpenMoves();
    },

    /**
     * Cashier stays in the core partner argument. The commercial contact,
     * documents and destination journal go in extras, same slot pos_hr uses
     * for employee_id.
     */
    _prepareTryCashInOutPayload() {
        const result = super._prepareTryCashInOutPayload(...arguments);
        const assign = {};
        if (this.state.partnerId) {
            assign.cash_partner_id = this.state.partnerId;
        }
        if (this.state.destJournalId) {
            assign.dest_journal_id = this.state.destJournalId;
        } else if (this.state.selectedMoveIds.length) {
            assign.move_ids = [...this.state.selectedMoveIds];
        }
        if (Object.keys(assign).length) {
            const index = result.length - 1;
            result[index] = { ...result[index], ...assign };
        }
        return result;
    },

    /**
     * SelectMenu calls this when the dropdown opens (empty string) and as
     * the cashier types. The widget already debounces keystrokes.
     */
    async onPartnerSearch(query) {
        const request = ++this._partnerRequest;
        try {
            const partners = await this.pos.data.call(
                "pos.session",
                "kai_search_cash_move_partners",
                [[this.pos.session.id], query || ""]
            );
            if (!this._alive || request !== this._partnerRequest) {
                return;
            }
            this.state.partnerChoices = this._partnerChoices(partners || []);
        } catch (error) {
            if (!this._alive || request !== this._partnerRequest) {
                return;
            }
            this.state.partnerChoices = this._partnerChoices([]);
            this.notification.add(this._rpcMessage(error, "No se pudieron buscar contactos."));
        }
    },

    onPartnerSelect(value) {
        if (!value) {
            this.clearPartner();
            return;
        }
        const choice = this.state.partnerChoices.find((item) => item.value === value);
        this.state.partnerId = value;
        this.state.partnerName = choice ? choice.label : this.state.partnerName;
        this.state.selectedMoveIds = [];
        this.loadOpenMoves();
    },

    clearPartner() {
        this.state.partnerId = false;
        this.state.partnerName = "";
        this.state.moves = [];
        this.state.selectedMoveIds = [];
    },

    _partnerChoices(partners) {
        const choices = partners.map((partner) => ({
            value: partner.id,
            label: partner.vat ? `${partner.name} · ${partner.vat}` : partner.name,
        }));
        if (
            this.state.partnerId &&
            !choices.some((choice) => choice.value === this.state.partnerId)
        ) {
            choices.unshift({
                value: this.state.partnerId,
                label: this.state.partnerName || "",
            });
        }
        return choices;
    },

    async loadOpenMoves() {
        if (!this.state.partnerId || this.state.destJournalId) {
            this.state.moves = [];
            this.state.loadingMoves = false;
            return;
        }
        const request = ++this._moveRequest;
        const partnerId = this.state.partnerId;
        const cashType = this.state.type;
        this.state.loadingMoves = true;
        try {
            const moves = await this.pos.data.call(
                "pos.session",
                "kai_list_cash_move_open_documents",
                [[this.pos.session.id], partnerId, cashType]
            );
            if (
                !this._alive ||
                request !== this._moveRequest ||
                this.state.partnerId !== partnerId ||
                this.state.destJournalId
            ) {
                return;
            }
            this.state.moves = moves || [];
        } catch (error) {
            if (!this._alive || request !== this._moveRequest) {
                return;
            }
            this.state.moves = [];
            this.notification.add(this._rpcMessage(error, "No se pudieron cargar las facturas."));
        } finally {
            if (this._alive && request === this._moveRequest) {
                this.state.loadingMoves = false;
            }
        }
    },

    async loadDestJournals() {
        try {
            const journals = await this.pos.data.call(
                "pos.session",
                "kai_list_cash_move_dest_journals",
                [[this.pos.session.id]]
            );
            if (!this._alive) {
                return;
            }
            this.state.journals = journals || [];
        } catch (error) {
            if (!this._alive) {
                return;
            }
            this.state.journals = [];
            this.notification.add(this._rpcMessage(error, "No se pudieron cargar los diarios."));
        }
    },

    onDestJournalChange(ev) {
        const value = parseInt(ev.target.value, 10);
        this.state.destJournalId = value || false;
        if (this.state.destJournalId) {
            this.state.selectedMoveIds = [];
            return;
        }
        if (this.state.partnerId) {
            this.loadOpenMoves();
        }
    },

    toggleMove(moveId) {
        const selected = new Set(this.state.selectedMoveIds);
        if (selected.has(moveId)) {
            selected.delete(moveId);
        } else {
            selected.add(moveId);
        }
        this.state.selectedMoveIds = [...selected];
    },

    isMoveSelected(moveId) {
        return this.state.selectedMoveIds.includes(moveId);
    },

    showOnAccount() {
        return Boolean(
            this.state.partnerId &&
                !this.state.destJournalId &&
                !this.state.selectedMoveIds.length &&
                !this.state.loadingMoves
        );
    },

    _rpcMessage(error, fallback) {
        return error?.data?.message || error?.message || fallback;
    },
});
