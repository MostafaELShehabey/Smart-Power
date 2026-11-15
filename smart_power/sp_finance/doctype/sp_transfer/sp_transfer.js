// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// SP Transfer (SP-117): the admin confirms (posts it) or rejects (with a reason) a pending transfer.
const SP_TF_API = "smart_power.sp_finance.transfer";

frappe.ui.form.on("SP Transfer", {
	setup(frm) {
		const money = () => ({ filters: { sp_account_kind: ["in", ["Official", "Transit"]], is_group: 0 } });
		frm.set_query("from_account", money);
		frm.set_query("to_account", money);
	},
	refresh(frm) {
		const colours = { Draft: "gray", Pending: "orange", Confirmed: "green", Rejected: "red" };
		frm.page.set_indicator(__(frm.doc.status), colours[frm.doc.status] || "gray");
		const admin = ["SP Admin", "System Manager"].some((r) => frappe.user.has_role(r));
		if (frm.doc.status !== "Pending" || !admin) return;
		frm.add_custom_button(__("Confirm"), async () => {
			await frappe.call({ method: `${SP_TF_API}.confirm`, args: { name: frm.doc.name }, freeze: true });
			frm.reload_doc();
		}).addClass("btn-primary");
		frm.add_custom_button(__("Reject"), () =>
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				async ({ reason }) => {
					await frappe.call({ method: `${SP_TF_API}.reject`, args: { name: frm.doc.name, reason }, freeze: true });
					frm.reload_doc();
				},
				__("Reject"),
				__("Reject")
			)
		);
	},
});
