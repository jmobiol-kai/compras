import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { CashMovePopup } from "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import "@kai_pos_cash_move_partner/app/cash_move_popup/cash_move_popup";

definePosModels();

test("switching cash in and cash out clears partner, documents and journal", async () => {
    const store = await setupPosEnv();
    store.data.call = async (model, method) => {
        if (method === "kai_list_cash_move_dest_journals") {
            return [{ id: 3, name: "Banco" }];
        }
        return [];
    };
    const popup = await mountWithCleanup(CashMovePopup, {
        props: { close: () => {} },
    });
    await animationFrame();
    popup.state.amount = "25";
    popup.state.reason = "Pago";
    popup.state.partnerId = 42;
    popup.state.partnerName = "Proveedor POS";
    popup.state.partnerChoices = [{ value: 42, label: "Proveedor POS" }];
    popup.state.moves = [{ id: 7, name: "FACT/001", amount_residual_display: "$ 10" }];
    popup.state.selectedMoveIds = [7];
    popup.state.journals = [{ id: 3, name: "Banco" }];
    await animationFrame();

    expect("#kai_cash_move_partner").toHaveValue("Proveedor POS");
    expect(".kai-cash-move-options input").toHaveCount(1);
    expect("#kai_cash_move_journal").toHaveValue("");

    // The popup opens on cash out. Clicking that direction again keeps the form.
    popup.onClickButton("out");
    await animationFrame();
    expect(popup.state.type).toBe("out");
    expect(popup.state.partnerId).toBe(42);
    expect(popup.state.selectedMoveIds).toEqual([7]);
    expect("#kai_cash_move_partner").toHaveValue("Proveedor POS");

    popup.onClickButton("in");
    await animationFrame();
    expect(popup.state.type).toBe("in");
    expect(popup.state.partnerId).toBe(false);
    expect(popup.state.partnerName).toBe("");
    expect(popup.state.partnerChoices).toEqual([]);
    expect(popup.state.moves).toEqual([]);
    expect(popup.state.selectedMoveIds).toEqual([]);
    expect(popup.state.destJournalId).toBe(false);
    expect(popup.state.loadingMoves).toBe(false);
    expect(popup.state.amount).toBe("25");
    expect(popup.state.reason).toBe("Pago");
    expect("#kai_cash_move_partner").toHaveValue("");
    expect("#kai_cash_move_journal").toHaveValue("");
    expect(".kai-cash-move-options").toHaveCount(0);

    popup.state.partnerId = 9;
    popup.state.partnerName = "Cliente";
    popup.state.partnerChoices = [{ value: 9, label: "Cliente" }];
    popup.state.destJournalId = 3;
    popup.state.selectedMoveIds = [8];
    await animationFrame();
    expect("#kai_cash_move_journal").toHaveValue("3");
    expect("#kai_cash_move_partner").toHaveValue("Cliente");

    popup.onClickButton("out");
    await animationFrame();
    expect(popup.state.type).toBe("out");
    expect(popup.state.partnerId).toBe(false);
    expect(popup.state.partnerName).toBe("");
    expect(popup.state.destJournalId).toBe(false);
    expect(popup.state.selectedMoveIds).toEqual([]);
    expect(popup.showDestJournal()).toBe(false);
    expect("#kai_cash_move_partner").toHaveValue("");
    expect("#kai_cash_move_journal").toHaveCount(0);
    expect("#kai_cash_move_journal_locked").toHaveCount(1);
});

test("cash out hides the destination journal until a contact is chosen", async () => {
    const store = await setupPosEnv();
    store.data.call = async (model, method) => {
        if (method === "kai_list_cash_move_dest_journals") {
            return [{ id: 3, name: "Banco" }];
        }
        return [];
    };
    const popup = await mountWithCleanup(CashMovePopup, {
        props: { close: () => {} },
    });
    await animationFrame();

    expect(popup.state.type).toBe("out");
    expect(popup.showDestJournal()).toBe(false);
    expect("#kai_cash_move_journal").toHaveCount(0);
    expect("#kai_cash_move_journal_locked").toHaveCount(1);

    popup.state.partnerId = 42;
    popup.state.partnerName = "Proveedor POS";
    popup.state.journals = [{ id: 3, name: "Banco" }];
    await animationFrame();
    expect(popup.showDestJournal()).toBe(true);
    expect("#kai_cash_move_journal").toHaveCount(1);
    expect("#kai_cash_move_journal_locked").toHaveCount(0);
    expect("#kai_cash_move_journal").toHaveValue("");

    popup.state.destJournalId = 3;
    await animationFrame();
    expect("#kai_cash_move_journal").toHaveValue("3");

    popup.clearPartner();
    await animationFrame();
    expect(popup.state.partnerId).toBe(false);
    expect(popup.state.destJournalId).toBe(false);
    expect("#kai_cash_move_journal").toHaveCount(0);
    expect("#kai_cash_move_journal_locked").toHaveCount(1);

    // Entrada can still pick a journal with no contact.
    popup.onClickButton("in");
    await animationFrame();
    expect(popup.state.type).toBe("in");
    expect(popup.showDestJournal()).toBe(true);
    expect("#kai_cash_move_journal").toHaveCount(1);
    expect("#kai_cash_move_journal_locked").toHaveCount(0);
    popup.state.destJournalId = 3;
    await animationFrame();
    expect(popup.state.partnerId).toBe(false);
    expect("#kai_cash_move_journal").toHaveValue("3");

    popup.onClickButton("out");
    await animationFrame();
    expect(popup.state.destJournalId).toBe(false);
    expect(popup.showDestJournal()).toBe(false);
    expect("#kai_cash_move_journal").toHaveCount(0);
    expect("#kai_cash_move_journal_locked").toHaveCount(1);
});

test("cash in with a contact and no invoice is pago a cuenta", async () => {
    const store = await setupPosEnv();
    store.data.call = async (model, method) => {
        if (method === "kai_list_cash_move_dest_journals") {
            return [{ id: 3, name: "Banco" }];
        }
        return [];
    };
    const popup = await mountWithCleanup(CashMovePopup, {
        props: { close: () => {} },
    });
    await animationFrame();
    popup.onClickButton("in");
    await animationFrame();
    popup.state.partnerId = 9;
    popup.state.partnerName = "Cliente";
    popup.state.moves = [{ id: 8, name: "FAC/008", amount_residual_display: "$ 10" }];
    popup.state.selectedMoveIds = [];
    popup.state.loadingMoves = false;
    await animationFrame();

    expect(popup.showOnAccount()).toBe(true);
    expect(popup.confirmWaitsForOpenMoves()).toBe(false);
    const note = popup.el.querySelector(".kai-cash-move-partner").textContent;
    expect(note.includes("recibo del cliente")).toBe(true);
    expect(note.includes("memo")).toBe(true);
    const payload = popup._prepareTryCashInOutPayload("in", 15, "Seña cumpleaños", 1, {
        translatedType: "in",
    });
    const extras = payload.at(-1);
    expect(payload[3]).toBe("Seña cumpleaños");
    expect(extras.cash_partner_id).toBe(9);
    expect(extras.move_ids).toBe(undefined);
    expect(extras.dest_journal_id).toBe(undefined);

    popup.state.loadingMoves = true;
    await animationFrame();
    expect(popup.confirmWaitsForOpenMoves()).toBe(true);
    expect(popup.showOnAccount()).toBe(false);
});
