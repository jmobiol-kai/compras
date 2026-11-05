import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { CashMovePopup } from "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import "@kai_pos_cash_move_partner/app/cash_move_popup/cash_move_popup";

definePosModels();

function destJournalsPayload() {
    return {
        journals: [{ id: 3, name: "Banco" }],
        session_cash_journal_id: 1,
        session_cash_journal_name: "Caja Blinis",
    };
}

test("switching cash in and cash out clears amount, reason, partner and journal", async () => {
    const store = await setupPosEnv();
    store.data.call = async (model, method) => {
        if (method === "kai_list_cash_move_dest_journals") {
            return destJournalsPayload();
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
    expect("#reason").toHaveValue("Pago");
    expect(".input-amount input.o_input").toHaveValue("25");

    // The popup opens on cash out. Clicking that direction again keeps the form.
    popup.onClickButton("out");
    await animationFrame();
    expect(popup.state.type).toBe("out");
    expect(popup.state.amount).toBe("25");
    expect(popup.state.reason).toBe("Pago");
    expect(popup.state.partnerId).toBe(42);
    expect(popup.state.selectedMoveIds).toEqual([7]);
    expect("#kai_cash_move_partner").toHaveValue("Proveedor POS");
    expect("#reason").toHaveValue("Pago");
    expect(".input-amount input.o_input").toHaveValue("25");

    popup.onClickButton("in");
    await animationFrame();
    expect(popup.state.type).toBe("in");
    expect(popup.state.amount).toBe("");
    expect(popup.state.reason).toBe("");
    expect(popup.state.partnerId).toBe(false);
    expect(popup.state.partnerName).toBe("");
    expect(popup.state.partnerChoices).toEqual([]);
    expect(popup.state.moves).toEqual([]);
    expect(popup.state.selectedMoveIds).toEqual([]);
    expect(popup.state.destJournalId).toBe(false);
    expect(popup.state.loadingMoves).toBe(false);
    expect("#reason").toHaveValue("");
    expect(".input-amount input.o_input").toHaveValue("");
    expect("#kai_cash_move_partner").toHaveValue("");
    expect("#kai_cash_move_journal").toHaveValue("");
    expect(".kai-cash-move-options").toHaveCount(0);

    popup.state.amount = "10";
    popup.state.reason = "Cobro";
    popup.state.partnerId = 9;
    popup.state.partnerName = "Cliente";
    popup.state.partnerChoices = [{ value: 9, label: "Cliente" }];
    popup.state.destJournalId = 3;
    popup.state.selectedMoveIds = [8];
    await animationFrame();
    expect("#kai_cash_move_journal").toHaveValue("3");
    expect("#kai_cash_move_partner").toHaveValue("Cliente");
    expect("#reason").toHaveValue("Cobro");
    expect(".input-amount input.o_input").toHaveValue("10");

    popup.onClickButton("out");
    await animationFrame();
    expect(popup.state.type).toBe("out");
    expect(popup.state.amount).toBe("");
    expect(popup.state.reason).toBe("");
    expect(popup.state.partnerId).toBe(false);
    expect(popup.state.partnerName).toBe("");
    expect(popup.state.destJournalId).toBe(false);
    expect(popup.state.selectedMoveIds).toEqual([]);
    expect("#reason").toHaveValue("");
    expect(".input-amount input.o_input").toHaveValue("");
    expect("#kai_cash_move_partner").toHaveValue("");
    expect("#kai_cash_move_journal").toHaveCount(1);
    expect("#kai_cash_move_journal").toHaveValue("");
    expect("#kai_cash_move_journal_locked").toHaveCount(0);
});

test("cash out keeps the destination journal selectable without a contact", async () => {
    const store = await setupPosEnv();
    store.data.call = async (model, method) => {
        if (method === "kai_list_cash_move_dest_journals") {
            return destJournalsPayload();
        }
        return [];
    };
    const popup = await mountWithCleanup(CashMovePopup, {
        props: { close: () => {} },
    });
    await popup.loadDestJournals();
    await animationFrame();

    expect(popup.state.type).toBe("out");
    expect(popup.state.partnerId).toBe(false);
    expect("#kai_cash_move_journal").toHaveCount(1);
    expect("#kai_cash_move_journal_locked").toHaveCount(0);
    expect("#kai_cash_move_journal").toHaveValue("");
    expect("#kai_cash_move_journal option[value='']").toHaveText("Caja Blinis");

    popup.state.journals = [{ id: 3, name: "Efectivo Tesoro" }];
    popup.onDestJournalChange({ target: { value: "3" } });
    await animationFrame();
    expect(popup.state.destJournalId).toBe(3);
    expect("#kai_cash_move_journal").toHaveValue("3");
    const tesoro = popup._prepareTryCashInOutPayload("out", 80, "A tesoro", 1, {}).at(-1);
    expect(tesoro.dest_journal_id).toBe(3);
    expect(tesoro.cash_partner_id).toBe(undefined);
    expect(tesoro.move_ids).toBe(undefined);

    // A contact added later, then cleared, does not drop the journal.
    popup.state.partnerId = 42;
    popup.state.partnerName = "Proveedor POS";
    popup.state.partnerChoices = [{ value: 42, label: "Proveedor POS" }];
    await animationFrame();
    popup.clearPartner();
    await animationFrame();
    expect(popup.state.partnerId).toBe(false);
    expect(popup.state.destJournalId).toBe(3);
    expect("#kai_cash_move_journal").toHaveValue("3");
    const stillTesoro = popup._prepareTryCashInOutPayload("out", 80, "A tesoro", 1, {}).at(-1);
    expect(stillTesoro.dest_journal_id).toBe(3);
    expect(stillTesoro.cash_partner_id).toBe(undefined);

    // Salida with a contact can still send the journal together with the partner.
    popup.state.partnerId = 42;
    popup.state.partnerName = "Proveedor POS";
    await animationFrame();
    const withPartner = popup._prepareTryCashInOutPayload("out", 80, "A tesoro", 1, {}).at(-1);
    expect(withPartner.dest_journal_id).toBe(3);
    expect(withPartner.cash_partner_id).toBe(42);

    // Entrada can still pick a journal with no contact.
    popup.onClickButton("in");
    await animationFrame();
    expect(popup.state.type).toBe("in");
    expect(popup.state.partnerId).toBe(false);
    expect(popup.state.destJournalId).toBe(false);
    expect("#kai_cash_move_journal").toHaveCount(1);
    expect("#kai_cash_move_journal_locked").toHaveCount(0);
    popup.onDestJournalChange({ target: { value: "3" } });
    await animationFrame();
    expect("#kai_cash_move_journal").toHaveValue("3");

    // Switching back to salida clears the journal picked on entrada, and the
    // selector stays available with no contact.
    popup.onClickButton("out");
    await animationFrame();
    expect(popup.state.destJournalId).toBe(false);
    expect(popup.state.partnerId).toBe(false);
    expect("#kai_cash_move_journal").toHaveCount(1);
    expect("#kai_cash_move_journal").toHaveValue("");
    expect("#kai_cash_move_journal_locked").toHaveCount(0);
});

test("empty destination option is the session cash journal on cash in and cash out", async () => {
    const store = await setupPosEnv();
    store.data.call = async (model, method) => {
        if (method === "kai_list_cash_move_dest_journals") {
            return destJournalsPayload();
        }
        return [];
    };
    const popup = await mountWithCleanup(CashMovePopup, {
        props: { close: () => {} },
    });
    await popup.loadDestJournals();
    await animationFrame();

    expect(popup.state.sessionCashJournalName).toBe("Caja Blinis");
    expect(popup.state.journals.map((journal) => journal.id)).toEqual([3]);
    expect(popup.state.type).toBe("out");
    expect(popup.state.partnerId).toBe(false);
    expect("#kai_cash_move_journal").toHaveCount(1);
    expect("#kai_cash_move_journal option[value='']").toHaveText("Caja Blinis");
    expect("#kai_cash_move_journal option[value='1']").toHaveCount(0);
    expect("#kai_cash_move_journal option[value='3']").toHaveCount(1);
    const salidaSinContacto = popup._prepareTryCashInOutPayload("out", 10, "Pago", 1, {}).at(-1);
    expect(salidaSinContacto.dest_journal_id).toBe(undefined);
    expect(salidaSinContacto.cash_partner_id).toBe(undefined);

    popup.state.partnerId = 42;
    popup.state.partnerName = "Proveedor POS";
    await animationFrame();
    expect("#kai_cash_move_journal option[value='']").toHaveText("Caja Blinis");
    const salida = popup._prepareTryCashInOutPayload("out", 10, "Pago", 1, {}).at(-1);
    expect(salida.dest_journal_id).toBe(undefined);
    expect(salida.cash_partner_id).toBe(42);

    popup.onClickButton("in");
    await animationFrame();
    expect("#kai_cash_move_journal").toHaveCount(1);
    expect("#kai_cash_move_journal option[value='']").toHaveText("Caja Blinis");
    expect(popup.state.destJournalId).toBe(false);
    const entrada = popup._prepareTryCashInOutPayload("in", 10, "Cobro", 1, {}).at(-1);
    expect(entrada.dest_journal_id).toBe(undefined);
    expect(entrada.cash_partner_id).toBe(undefined);
});

test("cash in with a contact and no invoice is pago a cuenta", async () => {
    const store = await setupPosEnv();
    store.data.call = async (model, method) => {
        if (method === "kai_list_cash_move_dest_journals") {
            return destJournalsPayload();
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
