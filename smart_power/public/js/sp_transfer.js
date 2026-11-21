// A4 Transfer / deposit (SP-117): from your own transit account (the admin: any money account) to
// another; pending until the admin confirms, except the admin's own official -> official, which
// posts at once. Used by the Treasury and the holder's profile. The rules are on the server
// (smart_power.sp_finance.transfer).
// SH3 (SP-105): the showroom cashier deposits the showroom box into an official account; the
// amount starts at the cash in hand (less the deposits already waiting for the admin).
frappe.provide("smart_power");

smart_power.transfer_dialog = async function (preset, on_done) {
	const API = "smart_power.sp_finance.transfer";
	const { message: opts } = await frappe.call({
		method: `${API}.transfer_options`,
		args: { company: (preset && preset.company) || null },
	});
	if (!opts.sources.length) {
		frappe.msgprint(__("You hold no money account to transfer from."));
		return;
	}
	const source = (account) => opts.sources.find((s) => s.value === account) || {};
	const balance = (account) => source(account).balance;
	const targets = (account) =>
		[{ value: "", label: "" }].concat(
			opts.destinations.filter((d) => d.value !== account && (!source(account).official_only || d.kind === "Official"))
		);
	const asked = preset && preset.from_account;
	const first = asked && source(asked).value ? asked : opts.sources[0].value;
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
				change: () => {
					const account = dialog.get_value("from_account");
					dialog.set_df_property("to_account", "options", targets(account));
					dialog.set_value("amount", balance(account) || 0);
				},
			},
			{
				fieldname: "to_account",
				fieldtype: "Select",
				label: __("To Account"),
				reqd: 1,
				options: targets(first),
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
