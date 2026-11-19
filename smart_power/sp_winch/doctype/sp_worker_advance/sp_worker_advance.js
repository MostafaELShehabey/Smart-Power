// Worker advance (SP-181): paid from an account, repaid by salary deduction or in cash.
// The rules are on the server (smart_power.sp_winch.crew_pay).
const SP_CREW_PAY_API = "smart_power.sp_winch.crew_pay";

frappe.ui.form.on("SP Worker Advance", {
	setup(frm) {
		// the crew picker: the winch manager may not read HR's Employee list
		frm.set_query("employee", () => ({ query: "smart_power.sp_core.workers.worker_query" }));
		frm.set_query("paid_from", () => ({
			query: "smart_power.sp_finance.queries.account_picker",
			filters: { company: frm.doc.company },
		}));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.status === "Open") {
			frm.add_custom_button(__("Repay in Cash"), () => sp_repay_in_cash(frm));
		}
	},
});

function sp_repay_in_cash(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Repay in Cash"),
		fields: [
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount"),
				reqd: 1,
				default: Math.min(frm.doc.installment_amount, frm.doc.outstanding_amount),
			},
			{
				fieldname: "to_account",
				fieldtype: "Link",
				options: "Account",
				label: __("To Account"),
				reqd: 1,
				get_query: () => ({
					query: "smart_power.sp_finance.queries.account_picker",
					filters: { company: frm.doc.company },
				}),
			},
			{
				fieldname: "repayment_date",
				fieldtype: "Date",
				label: __("Date"),
				default: frappe.datetime.get_today(),
				reqd: 1,
			},
		],
		primary_action_label: __("Save"),
		primary_action: async (values) => {
			await frappe.call({
				method: `${SP_CREW_PAY_API}.repay_in_cash`,
				args: { name: frm.doc.name, ...values },
				freeze: true,
			});
			dialog.hide();
			frm.reload_doc();
		},
	});
	dialog.show();
}
