// A2 Record a customer payment (SP-114): from the station (S2) or, for a deposit before the
// station exists, from the case. It is pending until the admin confirms it. The rules are on the
// server (smart_power.sp_finance.customer_payment).
frappe.provide("smart_power");

smart_power.record_payment_dialog = async function ({ station, case_name, is_deposit }, on_done) {
	const API = "smart_power.sp_finance.customer_payment";
	const { message: opts } = await frappe.call(`${API}.payment_options`, { station, case: case_name });
	const THIRD_PARTY = "Payment Method-THIRD_PARTY";
	const dialog = new frappe.ui.Dialog({
		title: is_deposit ? __("Record Deposit") : __("Record Payment"),
		fields: [
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount"),
				reqd: 1,
				default: opts.due || undefined,
			},
			{ fieldname: "work_date", fieldtype: "Date", label: __("Date"), reqd: 1, default: frappe.datetime.get_today() },
			{
				fieldname: "method",
				fieldtype: "Link",
				label: __("Method"),
				options: "SP List Value",
				reqd: 1,
				get_query: () => ({ filters: { list_name: "Payment Method", is_active: 1 } }),
			},
			{ fieldname: "col", fieldtype: "Column Break" },
			{
				fieldname: "receiving_account",
				fieldtype: "Select",
				label: __("Receiving Account"),
				options: [{ value: "", label: "" }].concat(opts.accounts),
				depends_on: `eval:doc.method !== "${THIRD_PARTY}"`,
				description: __("An official account, or your own transit account (cash in hand)."),
			},
			{ fieldname: "reference_no", fieldtype: "Data", label: __("Reference No.") },
			{
				fieldname: "receipt_photo",
				fieldtype: "Attach Image",
				label: __("Receipt Photo"),
				description: __("Needed unless it is cash into your own transit account."),
			},
			{
				fieldname: "third_section",
				fieldtype: "Section Break",
				label: __("Paid to a Third Party"),
				depends_on: `eval:doc.method === "${THIRD_PARTY}"`,
			},
			{
				fieldname: "third_party_type",
				fieldtype: "Select",
				label: __("Payee Type"),
				options: ["", "Supplier", "Account"],
			},
			{ fieldname: "third_party", fieldtype: "Dynamic Link", label: __("Payee"), options: "third_party_type" },
		],
		primary_action_label: __("Record"),
		primary_action: async (values) => {
			const { message: name } = await frappe.call({
				method: `${API}.record_payment`,
				args: { values: { ...values, station, case: case_name, is_deposit: is_deposit ? 1 : 0 } },
				freeze: true,
			});
			dialog.hide();
			frappe.show_alert({ message: __("{0} recorded: pending the admin's confirmation.", [name]), indicator: "orange" });
			on_done && on_done(name);
		},
	});
	dialog.show();
};
