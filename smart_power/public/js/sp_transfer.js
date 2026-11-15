// A4 Transfer / deposit (SP-117): from your own transit account (the admin: any money account) to
// another; pending until the admin confirms, except the admin's own official -> official, which
// posts at once. Used by the Treasury and the holder's profile. The rules are on the server
// (smart_power.sp_finance.transfer).
frappe.provide("smart_power");

smart_power.transfer_dialog = async function (preset, on_done) {
	const API = "smart_power.sp_finance.transfer";
	const { message: opts } = await frappe.call(`${API}.transfer_options`);
	if (!opts.sources.length) {
		frappe.msgprint(__("You hold no money account to transfer from."));
		return;
	}
	const balance = (account) => (opts.sources.find((s) => s.value === account) || {}).balance;
	const first = (preset && preset.from_account) || opts.sources[0].value;
	const dialog = new frappe.ui.Dialog({
		title: __("Transfer / Deposit"),
		fields: [
			{
				fieldname: "from_account",
				fieldtype: "Select",
				label: __("From Account"),
				reqd: 1,
				options: opts.sources.map((s) => ({ value: s.value, label: `${s.label} (${format_currency(s.balance)})` })),
				default: first,
				change: () => dialog.set_value("amount", balance(dialog.get_value("from_account")) || 0),
			},
			{
				fieldname: "to_account",
				fieldtype: "Select",
				label: __("To Account"),
				reqd: 1,
				options: [{ value: "", label: "" }].concat(opts.destinations),
			},
			{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"), reqd: 1, default: balance(first) || undefined },
			{ fieldname: "col", fieldtype: "Column Break" },
			{ fieldname: "work_date", fieldtype: "Date", label: __("Date"), reqd: 1, default: frappe.datetime.get_today() },
			{ fieldname: "reference_no", fieldtype: "Data", label: __("Reference No.") },
			{
				fieldname: "receipt_photo",
				fieldtype: "Attach Image",
				label: __("Receipt Photo"),
				description: __("The deposit slip or transfer screenshot."),
			},
		],
		primary_action_label: __("Record"),
		primary_action: async (values) => {
			const { message: name } = await frappe.call({
				method: `${API}.record_transfer`,
				args: { values },
				freeze: true,
			});
			dialog.hide();
			frappe.show_alert({ message: __("{0} recorded.", [name]), indicator: "green" });
			on_done && on_done(name);
		},
	});
	dialog.show();
};
