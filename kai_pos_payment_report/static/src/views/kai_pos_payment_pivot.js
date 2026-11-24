/** @odoo-module **/

import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";
import { pivotView } from "@web/views/pivot/pivot_view";

export class KaiPosPaymentPivotRenderer extends PivotRenderer {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.canExportPlanilla = false;
        onWillStart(async () => {
            this.canExportPlanilla = await user.hasGroup(
                "kai_pos_payment_report.group_pos_payment_journal_report"
            );
        });
    }

    onExportPlanillaClicked() {
        this.actionService.doAction("kai_pos_payment_report.action_pos_payment_report_export");
    }
}

export const kaiPosPaymentPivotView = {
    ...pivotView,
    Renderer: KaiPosPaymentPivotRenderer,
    buttonTemplate: "kai_pos_payment_report.PivotView.Buttons",
};

registry.category("views").add("kai_pos_payment_pivot", kaiPosPaymentPivotView);
