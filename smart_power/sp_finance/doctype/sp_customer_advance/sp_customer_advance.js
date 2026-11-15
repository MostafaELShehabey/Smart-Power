// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A8 Customer advances, Agri Bank (SP-121): the advance paid for the customer's own share, and its
// repayments (the bank's release or the customer) with an optional fee. The posting is on the
// server (smart_power.sp_finance.advances).
const SP_ADV_API = "smart_power.sp_finance.advances";
const SP_ADV_COLOURS = {
	Draft: "gray",
	Open: "blue",
	"Partly repaid": "orange",
	Repaid: "green",
	"Unpaid - overdue": "red",
	Cancelled: "red",
};

const sp_official = (frm) => ({
	filters: { company: frm.doc.company, sp_account_kind: "Official", is_group: 0, disabled: 0 },
});

frappe.ui.form.on("SP Customer Advance", {
	setup(frm) {
		frm.set_query("paid_from_account", () => sp_official(frm));
	},
	refresh(frm) {
		frm.page.set_indicator(__(frm.doc.status), SP_ADV_COLOURS[frm.doc.status] || "gray");
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.status !== "Repaid") {
			frm.add_custom_button(__("Add Repayment"), () => sp_add_repayment(frm)).addClass("btn-primary");
			if (frm.doc.status !== "Unpaid - overdue") {
				frm.add_custom_button(__("Mark Unpaid"), () =>
					frappe.prompt(
						{ fieldname: "note", fieldtype: "Small Text", label: __("Note"), reqd: 1 },
						async ({ note }) => {
							await frappe.call({
								method: `${SP_ADV_API}.mark_unpaid`,
								args: { name: frm.doc.name, note },
								freeze: true,
							});
							frm.reload_doc();
						},
						__("Unpaid advance"),
						__("Mark Unpaid"),
					),
				);
			}
		}
	},
});

function sp_add_repayment(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Repayment of {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Repaid"),
				default: frm.doc.outstanding_amount,
				description: __("Outstanding: {0}", [format_currency(frm.doc.outstanding_amount)]),
			},
			{ fieldname: "fee_amount", fieldtype: "Currency", label: __("Fee") },
			{
				fieldname: "to_account",
				fieldtype: "Link",
				options: "Account",
				label: __("To Account"),
				reqd: 1,
				get_query: () => sp_official(frm),
			},
			{ fieldname: "repayment_date", fieldtype: "Date", label: __("Date"), default: "Today", reqd: 1 },
			{ fieldname: "reference", fieldtype: "Data", label: __("Reference") },
		],
		primary_action_label: __("Post Repayment"),
		async primary_action(values) {
			await frappe.call({
				method: `${SP_ADV_API}.add_repayment`,
				args: { name: frm.doc.name, ...values },
				freeze: true,
			});
			d.hide();
			frm.reload_doc();
		},
	});
	d.show();
}
