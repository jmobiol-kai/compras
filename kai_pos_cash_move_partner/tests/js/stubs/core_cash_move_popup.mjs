export class CashMovePopup {
    static components = {};

    onClickButton(type) {
        this.state.type = type;
        this.inputRef.el.focus();
    }

    _prepareTryCashInOutPayload(type, amount, reason, partnerId, extras) {
        return [[this.pos.session.id], type, amount, reason, partnerId, extras];
    }
}
