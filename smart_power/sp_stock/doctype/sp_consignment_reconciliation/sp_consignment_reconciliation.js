// I7 Consignment reconciliation (SP-93): load our container figures, type the supplier's statement,
// then finish. The rules are on the server (smart_power.sp_stock.consignment_reconciliation).
const SP_CRC_API = "smart_power.sp_stock.consignment_reconciliation";

frappe.ui.form.on("SP Consignment Reconciliation", {
	setup(frm) {
		frm.set_query("supplier", () => ({ filters: { sp_is_consignment_owner: 1 } }));
		// a differing container shows red in the grid, a matching one green
		frm.set_indicator_formatter("container", (row) => (row.line_status === "Difference" ? "red" : row.line_status ? "green" : "gray"));
	},

	onload(frm) {
		if (frm.is_new() && !frm.doc.period) {
			// the month just closed, as the monthly sheet covers
			frm.set_value("period", frappe.datetime.add_months(frappe.datetime.month_start(), -1));
		}
	},

	refresh(frm) {
		frm.fields_dict.lines.grid.cannot_add_rows = true;
		if (frm.is_new()) return;
		if (frm.doc.status !== "Draft") {
			frm.disable_form();
			return;
		}
		frm.add_custom_button(__("Load Containers"), async () => {
			if (frm.is_dirty()) await frm.save();
			const { message } = await frappe.call({ method: `${SP_CRC_API}.load`, args: { name: frm.doc.name }, freeze: true });
			frappe.show_alert({ message: __("{0} containers loaded", [message.lines]), indicator: "blue" });
			frm.reload_doc();
		});
		frm.page.set_primary_action(__("Finish Reconciliation"), async () => {
			if (frm.is_dirty()) await frm.save();
			const diffs = (frm.doc.lines || []).filter((l) => l.line_status === "Difference").length;
			const question = diffs
				? __("Finish with {0} differences? The admin will be told.", [diffs])
				: __("Finish as matched? Every container agrees with the statement.");
			frappe.confirm(question, async () => {
				const { message } = await frappe.call({ method: `${SP_CRC_API}.finish`, args: { name: frm.doc.name }, freeze: true });
				frappe.show_alert({
					message: message.differences ? __("Saved with differences: the admin has been told") : __("Reconciliation matched"),
					indicator: message.differences ? "orange" : "green",
				});
				frm.reload_doc();
			});
		});
	},
});
