// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// R5 Team commission (SP-143): Mark Paid posts one person's payment from an official account.
frappe.ui.form.on("SP Team Commission", {
	refresh(frm) {
		if (frm.is_new() || frm.is_dirty()) return;
		const unpaid = (frm.doc.lines || []).filter((row) => !row.paid);
		if (unpaid.length && frm.has_perm("write")) {
			frm.add_custom_button(__("Mark Paid"), () => mark_paid(frm, unpaid));
		}
	},
});

function mark_paid(frm, unpaid) {
	const dialog = new frappe.ui.Dialog({
		title: __("Mark Paid"),
		fields: [
			{
				fieldname: "line",
				label: __("Person"),
				fieldtype: "Select",
				reqd: 1,
				options: unpaid.map((row) => ({
					value: row.name,
					label: `${row.full_name || row.user} (${format_currency(row.amount)})`,
				})),
			},
			{
				fieldname: "account",
				label: __("Paid From"),
				fieldtype: "Link",
				options: "Account",
				reqd: 1,
				get_query: () => ({
					filters: { company: frm.doc.company, sp_account_kind: "Official", is_group: 0, disabled: 0 },
				}),
			},
			{ fieldname: "paid_on", label: __("Paid On"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		],
		primary_action_label: __("Mark Paid"),
		primary_action(values) {
			frappe
				.call("smart_power.sp_finance.team_commission.mark_paid", { name: frm.doc.name, ...values })
				.then(() => {
					dialog.hide();
					frm.reload_doc();
				});
		},
	});
	dialog.show();
}
