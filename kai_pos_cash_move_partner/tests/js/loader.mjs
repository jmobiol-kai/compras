const stubs = {
    "@point_of_sale/app/components/popups/cash_move_popup/cash_move_popup": new URL(
        "./stubs/core_cash_move_popup.mjs",
        import.meta.url
    ),
    "@web/core/select_menu/select_menu": new URL("./stubs/select_menu.mjs", import.meta.url),
    "@web/core/utils/patch": new URL("./stubs/patch.mjs", import.meta.url),
    "@odoo/owl": new URL("./stubs/owl.mjs", import.meta.url),
};

export async function resolve(specifier, context, nextResolve) {
    const stub = stubs[specifier];
    if (stub) {
        return { url: stub.href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
}
