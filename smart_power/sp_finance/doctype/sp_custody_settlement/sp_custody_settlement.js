// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A9 Custody settlement (SP-122): the holder's expenses with their receipts. The admin approves
// (A1 or here): mark an expense Reject with its reason and it goes back to the holder; the rest
// post to their stations and centers. The rules are on the server (smart_power.sp_finance.custody).
const SP_CST_API = "smart_power.sp_finance.custody";
const SP_CST_COLOURS = { Draft: "gray", Pending: "orange", Approved: "green", Rejected: "red" };

frappe.ui.form.on("SP Custody Settlement", {
	setup(frm) {
		frm.set_query("return_to_account", () => ({
			filters: { company: frm.doc.company, sp_account_kind: "Official", is_group: 0, disabled: 0 },
		}));
	},
	refresh(frm) {
		frm.page.set_indicator(__(frm.doc.status), SP_CST_COLOURS[frm.doc.status] || "gray");
		const admin = ["SP Admin", "System Manager"].some((r) => frappe.user.has_role(r));
		if (frm.doc.status !== "Pending" || !admin) return;
		frm.add_custom_button(__("Approve"), async () => {
			if (frm.is_dirty()) await frm.save("Update");
			const rejected = (frm.doc.lines || []).filter((r) => r.decision === "Reject").length;
			const message = rejected
				? __("Approve {0}? {1} expense(s) go back to the holder.", [frm.doc.name, rejected])
				: __("Approve {0}? Every expense posts to its center.", [frm.doc.name]);
			frappe.confirm(message, async () => {
				await frappe.call({ method: `${SP_CST_API}.confirm`, args: { name: frm.doc.name }, freeze: true });
				frm.reload_doc();
			});
		}).addClass("btn-primary");
		frm.add_custom_button(__("Reject"), () =>
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				async ({ reason }) => {
					await frappe.call({ method: `${SP_CST_API}.reject`, args: { name: frm.doc.name, reason }, freeze: true });
					frm.reload_doc();
				},
				__("Reject the settlement"),
				__("Reject")
			)
		);
	},
});
