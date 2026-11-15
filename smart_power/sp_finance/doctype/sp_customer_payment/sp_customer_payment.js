// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// SP Customer Payment (SP-114): the admin confirms (posts it) or rejects (with a reason) a pending
// payment. The rules are on the server (smart_power.sp_finance.customer_payment).
const SP_CP_API = "smart_power.sp_finance.customer_payment";
const SP_CP_ADMIN_ROLES = ["SP Admin", "System Manager"];

frappe.ui.form.on("SP Customer Payment", {
	setup(frm) {
		frm.set_query("receiving_account", () => ({
			query: `${SP_CP_API}.account_query`,
			filters: { company: frm.doc.company },
		}));
		frm.set_query("method", () => ({ filters: { list_name: "Payment Method", is_active: 1 } }));
	},
	refresh(frm) {
		const colours = { Draft: "gray", Pending: "orange", Confirmed: "green", Rejected: "red" };
		frm.page.set_indicator(__(frm.doc.status), colours[frm.doc.status] || "gray");
		const admin = SP_CP_ADMIN_ROLES.some((r) => frappe.user.has_role(r));
		if (frm.doc.status !== "Pending" || !admin) return;
		frm.add_custom_button(__("Confirm"), () =>
			frappe.confirm(__("Confirm {0} received into {1}? It is posted now.", [format_currency(frm.doc.amount), frm.doc.receiving_account || frm.doc.third_party]), async () => {
				await frappe.call({ method: `${SP_CP_API}.confirm`, args: { name: frm.doc.name }, freeze: true });
				frm.reload_doc();
			})
		).addClass("btn-primary");
		frm.add_custom_button(__("Reject"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				async ({ reason }) => {
					await frappe.call({ method: `${SP_CP_API}.reject`, args: { name: frm.doc.name, reason }, freeze: true });
					frm.reload_doc();
				},
				__("Reject Payment"),
				__("Reject")
			);
		});
	},
});
