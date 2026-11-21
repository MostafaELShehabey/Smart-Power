// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A10 Expense (SP-123): the type, the center (a station's, or the indirect pool), what paid it.
frappe.ui.form.on("SP Expense", {
	setup(frm) {
		frm.set_query("expense_type", () => ({ filters: { list_name: "Expense Type", is_active: 1 } }));
		frm.set_query("paid_from_account", () => ({
			filters: { company: frm.doc.company, sp_account_kind: "Official", is_group: 0, disabled: 0 },
		}));
		// Submit posts money: show exactly the entry first (SP-44)
		frm.savesubmit = async function () {
			const lines = await frappe.xcall("smart_power.sp_finance.expenses.preview", { doc: frm.doc });
			sp.ui.confirm_irreversible(__("Submit and post"), sp.ui.entry_preview_html(lines), () => frm.save("Submit"));
		};
	},
	onload(frm) {
		if (frm.is_new() && !frm.doc.company) {
			frm.set_value("company", frappe.defaults.get_user_default("Company"));
		}
		// the showroom cashier pays from the shop cash only
		const full = ["SP Admin", "System Manager", "SP Accountant"].some((r) => frappe.user.has_role(r));
		if (!full) {
			frm.set_value("paid_from_kind", "Shop cash");
			frm.set_df_property("paid_from_kind", "read_only", 1);
		}
	},
	center_type(frm) {
		if (frm.doc.center_type !== "Project") frm.set_value("station", null);
	},
});
