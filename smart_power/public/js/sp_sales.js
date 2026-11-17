// Sales dialogs shared by the case and the customer record (SP-67 F3, SP-50).
//   sp.sales.log_call_dialog(case, on_done)   log a call on a case; a "Lost" result asks
//                                              for the lost reason next
//   sp.sales.lost_dialog(case, note, on_done)
window.sp = window.sp || {};
sp.sales = sp.sales || {};

sp.sales.log_call_dialog = function (case_name, on_done) {
	const dialog = new frappe.ui.Dialog({
		title: __("Log call"),
		fields: [
			{
				fieldname: "result",
				fieldtype: "Link",
				label: __("Result"),
				options: "SP List Value",
				reqd: 1,
				get_query: () => ({ filters: { list_name: "Call Result", is_active: 1 } }),
			},
			{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			{
				fieldname: "next_call_at",
				fieldtype: "Datetime",
				label: __("Next Call"),
				description: __("Becomes a call task for the follow-up owner."),
			},
		],
		primary_action_label: __("Save"),
		primary_action: async (values) => {
			const { message } = await frappe.call({
				method: "smart_power.sp_sales.followup.log_call",
				args: { case: case_name, ...values },
				freeze: true,
			});
			dialog.hide();
			if (message && message.lost) {
				sp.sales.lost_dialog(case_name, values.note, on_done);
			} else if (on_done) {
				on_done();
			}
		},
	});
	dialog.show();
	return dialog;
};

sp.sales.lost_dialog = function (case_name, note, on_done) {
	const dialog = new frappe.ui.Dialog({
		title: __("Mark Lost"),
		fields: [
			{
				fieldname: "lost_reason",
				fieldtype: "Link",
				label: __("Lost Reason"),
				options: "SP List Value",
				reqd: 1,
				get_query: () => ({ filters: { list_name: "Lost Reason", is_active: 1 } }),
			},
			{ fieldname: "lost_note", fieldtype: "Small Text", label: __("Lost Note"), default: note },
		],
		primary_action_label: __("Mark Lost"),
		primary_action: async (values) => {
			await frappe.call({
				method: "smart_power.sp_sales.followup.mark_lost",
				args: { case: case_name, ...values },
				freeze: true,
			});
			dialog.hide();
		},
	});
	dialog.on_hide = () => on_done && on_done();
	dialog.show();
	return dialog;
};

// Q1 "Duplicate for Customer" (SP-64): the quote's lines into a new case for another customer,
// as its first draft version. From the quote form and the quotes list.
sp.sales.duplicate_quote = function (quotation) {
	const d = new frappe.ui.Dialog({
		title: __("Duplicate for Customer"),
		fields: [
			{
				fieldname: "customer",
				label: __("Customer"),
				fieldtype: "Link",
				options: "Customer",
				reqd: 1,
				description: __("A new case is opened for this customer with a draft copy of {0}.", [quotation]),
			},
		],
		primary_action_label: __("Duplicate for Customer"),
		primary_action: async ({ customer }) => {
			const { message } = await frappe.call({
				method: "smart_power.sp_sales.quote_list.duplicate_for_customer",
				args: { name: quotation, customer },
				freeze: true,
			});
			d.hide();
			frappe.show_alert({ message: __("Case {0} opened with draft {1}.", [message.case, message.quotation]), indicator: "green" });
			frappe.set_route("Form", "Quotation", message.quotation);
		},
	});
	d.show();
};

// "Intends to proceed" (SP-70): the option the customer took becomes the approved version, the
// admin gets a technical review task and the projects managers are told. The case is won when
// the deposit on that version is confirmed. From the follow-up board (a drop on Won) and the case.
sp.sales.intends_to_proceed = async function (case_name, on_done) {
	const { message: options } = await frappe.call("smart_power.sp_sales.board.won_options", { case: case_name });
	if (!options || !options.length) {
		frappe.msgprint(__("Send a quote before saying the customer will go ahead."));
		return;
	}
	const label = (q) =>
		`${q.name} · ${__("Option")} ${q.sp_option_label || "A"} · ${__("Version")} ${q.sp_version || ""} · ${format_currency(
			q.total,
			q.currency
		)}`;
	const approved = options.find((q) => q.sp_is_approved) || options[0];
	const dialog = new frappe.ui.Dialog({
		title: __("Intends to Proceed"),
		fields: [
			{
				fieldname: "quotation",
				fieldtype: "Select",
				label: __("The option the customer took"),
				reqd: 1,
				options: options.map((q) => ({ value: q.name, label: label(q) })),
				default: approved.name,
			},
			{ fieldname: "note", fieldtype: "Small Text", label: __("Note for the technical review") },
			{
				fieldname: "explain",
				fieldtype: "HTML",
				options: `<p class="text-muted small">${frappe.utils.escape_html(
					__("The case is won when the deposit on this version is confirmed.")
				)}</p>`,
			},
		],
		primary_action_label: __("Intends to Proceed"),
		primary_action: async (values) => {
			await frappe.call({
				method: "smart_power.sp_sales.board.intends_to_proceed",
				args: { case: case_name, quotation: values.quotation, note: values.note || null },
				freeze: true,
			});
			dialog.hide();
			frappe.show_alert({ message: __("The admin has a technical review task."), indicator: "green" });
			if (on_done) on_done();
		},
	});
	dialog.show();
};
