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
    expect("#kai_cash_move_partner").toHaveValue("");
    expect("#kai_cash_move_journal").toHaveValue("");
});
