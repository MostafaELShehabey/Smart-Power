// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A9 Custody (SP-122), the admin's view: give custody from an official account to a holder; the
// holder's expenses, what is approved, and the holder's custody balance. The holder records and
// settles from My Custody. The rules are on the server (smart_power.sp_finance.custody).
const SP_CUS_COLOURS = {
	Draft: "gray",
	Given: "blue",
	Spending: "orange",
	"Settlement submitted": "purple",
	Approved: "green",
	Carried: "green",
	Returned: "gray",
	Cancelled: "red",
};

frappe.ui.form.on("SP Custody", {
	setup(frm) {
		frm.set_query("from_account", () => ({
			filters: { company: frm.doc.company, sp_account_kind: "Official", is_group: 0, disabled: 0 },
		}));
		frm.set_query("holder", () => ({
			query: "frappe.core.doctype.user.user.user_query",
			filters: { ignore_user_type: 1 },
		}));
	},
	refresh(frm) {
		frm.page.set_indicator(__(frm.doc.status), SP_CUS_COLOURS[frm.doc.status] || "gray");
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("My Custody"), () =>
				frappe.set_route("sp-my-custody", { holder: frm.doc.holder })
			);
		}
	},
});
