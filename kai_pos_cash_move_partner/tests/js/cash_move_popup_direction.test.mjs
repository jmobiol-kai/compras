// State machine of the POS cash-move popup. Run from the repo root:
//   node kai_pos_cash_move_partner/tests/js/cash_move_popup_direction.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { register } from "node:module";

await register(new URL("./loader.mjs", import.meta.url), {
    parentURL: import.meta.url,
});

await import("../../static/src/app/cash_move_popup/cash_move_popup.js");
const { CashMovePopup } = await import(
    "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup"
);

function makePopup(extra = {}) {
    const popup = Object.create(CashMovePopup.prototype);
    popup.state = {
        type: "out",
        amount: "",
        reason: "",
        partnerId: false,
        partnerName: "",
        partnerChoices: [],
        moves: [],
        selectedMoveIds: [],
        journals: [],
        destJournalId: false,
        loadingMoves: false,
        ...extra,
    };
    popup._alive = true;
    popup._moveRequest = 0;
    popup._partnerRequest = 0;
    popup.inputRef = { el: { focus() {} } };
    popup.notification = { add() {} };
    popup.pos = {
        session: { id: 1 },
        data: {
            async call() {
                return [];
            },
        },
    };
    return popup;
}

function extrasOf(popup) {
    const payload = popup._prepareTryCashInOutPayload("out", 10, "Pago", 1, {});
    return payload[payload.length - 1];
}

const xml = readFileSync(
    new URL("../../static/src/app/cash_move_popup/cash_move_popup.xml", import.meta.url),
    "utf8"
);
assert.match(xml, /<SelectMenu\s+t-key="state\.type"/);
assert.match(
    xml,
    /id="kai_cash_move_journal"[\s\S]*?t-key="state\.type"[\s\S]*?t-att-value="state\.destJournalId \|\| ''"/
);

{
    const popup = makePopup({
        amount: "25",
        reason: "Pago",
        partnerId: 42,
        partnerName: "Proveedor POS",
        partnerChoices: [{ value: 42, label: "Proveedor POS" }],
        moves: [{ id: 7, name: "FACT/001" }],
        selectedMoveIds: [7],
        destJournalId: 3,
        loadingMoves: true,
    });
    assert.equal(extrasOf(popup).cash_partner_id, 42);
    assert.equal(extrasOf(popup).dest_journal_id, 3);
    assert.equal(extrasOf(popup).move_ids, undefined);

    popup.onClickButton("out");
    assert.equal(popup.state.partnerId, 42);
    assert.equal(popup.state.destJournalId, 3);
    assert.deepEqual(popup.state.selectedMoveIds, [7]);

    popup.onClickButton("in");
    assert.equal(popup.state.type, "in");
    assert.equal(popup.state.partnerId, false);
    assert.equal(popup.state.partnerName, "");
    assert.deepEqual(popup.state.partnerChoices, []);
    assert.deepEqual(popup.state.moves, []);
    assert.deepEqual(popup.state.selectedMoveIds, []);
    assert.equal(popup.state.destJournalId, false);
    assert.equal(popup.state.loadingMoves, false);
    assert.equal(popup.state.amount, "25");
    assert.equal(popup.state.reason, "Pago");
    const cleared = extrasOf(popup);
    assert.equal(cleared.cash_partner_id, undefined);
    assert.equal(cleared.dest_journal_id, undefined);
    assert.equal(cleared.move_ids, undefined);

    popup.state.partnerId = 9;
    popup.state.partnerName = "Cliente";
    popup.state.moves = [{ id: 8 }];
    popup.state.selectedMoveIds = [8];
    popup.state.destJournalId = 4;
    popup.onClickButton("out");
    assert.equal(popup.state.type, "out");
    assert.equal(popup.state.partnerId, false);
    assert.deepEqual(popup.state.selectedMoveIds, []);
    assert.equal(popup.state.destJournalId, false);
    assert.deepEqual(popup.state.moves, []);
}

{
    const popup = makePopup({
        partnerId: 42,
        partnerName: "Proveedor",
        moves: [{ id: 7 }, { id: 8 }],
        selectedMoveIds: [7, 8],
    });
    assert.deepEqual(extrasOf(popup).move_ids, [7, 8]);
    assert.equal(extrasOf(popup).cash_partner_id, 42);
    popup.onClickButton("in");
    const cleared = extrasOf(popup);
    assert.equal(cleared.cash_partner_id, undefined);
    assert.equal(cleared.move_ids, undefined);
    assert.equal(cleared.dest_journal_id, undefined);
}

{
    const popup = makePopup({ partnerId: 5, partnerName: "Proveedor" });
    let release;
    popup.pos.data.call = () =>
        new Promise((resolve) => {
            release = resolve;
        });
    const pending = popup.loadOpenMoves();
    assert.equal(popup.state.loadingMoves, true);
    popup.onClickButton("in");
    release([{ id: 99, name: "BILL/099" }]);
    await pending;
    assert.deepEqual(popup.state.moves, []);
    assert.equal(popup.state.loadingMoves, false);
    assert.equal(popup.state.partnerId, false);
}

{
    const popup = makePopup();
    let release;
    popup.pos.data.call = (model, method, args) =>
        new Promise((resolve) => {
            release = () => resolve([{ id: args[1], name: "Contacto" }]);
        });
    const pending = popup.onPartnerSearch("Pro");
    popup.onClickButton("in");
    release();
    await pending;
    assert.deepEqual(popup.state.partnerChoices, []);
    assert.equal(popup.state.partnerId, false);
}

console.log("cash move direction reset: ok");
