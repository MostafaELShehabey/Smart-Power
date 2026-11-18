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

// Send a quote version (SP-61, SP-63): from the quote form and the Quote Builder.
const SP_SEND_API = "smart_power.sp_quotes.quote_send";

sp.sales.send_quote = async function (quotation, docstatus, on_done) {
	const { message: opts } = await frappe.call(`${SP_SEND_API}.send_options`, { quotation });
	const dialog = new frappe.ui.Dialog({
		title: docstatus === 0 ? __("Send to Customer") : __("Send Again"),
		fields: [
			{
				fieldname: "print_format",
				fieldtype: "Select",
				label: __("Print Format"),
				options: opts.formats,
				default: opts.default,
				reqd: 1,
			},
			{
				fieldname: "channel",
				fieldtype: "Select",
				label: __("Channel"),
				options: opts.channels.map((c) => ({ value: c, label: __(c) })),
				default: "WhatsApp",
				reqd: 1,
			},
			{
				fieldname: "note",
				fieldtype: "HTML",
				options: `<p class="text-muted small">${frappe.utils.escape_html(
					docstatus === 0
						? __("Sending freezes this version: it cannot be edited afterwards.")
						: __("A new PDF is made and logged for this send.")
				)}</p>`,
			},
			...sp_quote_price_age_fields(opts.price_age || {}),
			...sp_quote_technical_fields(opts.technical || {}, (opts.price_age?.warn || []).length > 0),
		],
		primary_action_label: __("Send"),
		primary_action: async (values) => {
			dialog.hide();
			const { message: r } = await frappe.call({
				method: `${SP_SEND_API}.send_quote`,
				args: { quotation, ...values, reason: values.reason || null },
				freeze: true,
				freeze_message: __("Making the PDF…"),
			});
			(r.warnings || []).forEach((w) => frappe.show_alert({ message: w, indicator: "orange" }, 10)); // sp-allow-number: seconds on screen
			frappe.show_alert({ message: __("Quote sent"), indicator: "green" });
			await sp_quote_share(r, values.channel, quotation);
			if (on_done) on_done();
		},
	});
	dialog.show();
	// a stale price of a Block category: the quote is not sent until the price is updated
	if ((opts.price_age?.block || []).length) dialog.get_primary_btn().prop("disabled", true);
	// a technical rule at Block: only the admin can pass it, with a reason (SP-169)
	if ((opts.technical?.block || []).length && !opts.technical.can_override) {
		dialog.get_primary_btn().prop("disabled", true);
	}
};

// technical rules at send (SP-169): a red banner at Block, an orange one at Warn
function sp_quote_technical_fields(technical, has_reason) {
	const esc = frappe.utils.escape_html;
	const banner = (name, kind, rows) => ({
		fieldname: name,
		fieldtype: "HTML",
		options: `<div class="alert alert-${kind} small">${rows.map(esc).join("<br>")}</div>`,
	});
	const fields = [];
	const blocked = technical.block || [];
	if (blocked.length) {
		fields.push(banner("technical_block", "danger", blocked));
		if (technical.can_override && !has_reason) {
			fields.push({ fieldname: "reason", fieldtype: "Small Text", label: __("Reason for overriding"), reqd: 1 });
		}
	}
	if ((technical.warn || []).length) fields.push(banner("technical_warn", "warning", technical.warn));
	return fields;
}

// stale prices at send (SP-63): a red banner naming them at Block, a reason at Warn
function sp_quote_price_age_fields(price_age) {
	const esc = frappe.utils.escape_html;
	const names = (rows) =>
		rows.map((r) => `${r.item_name} (${__("{0} days, limit {1}", [r.age_days, r.max_days])})`).join(", ");
	if ((price_age.block || []).length) {
		return [
			{
				fieldname: "price_block",
				fieldtype: "HTML",
				options: `<div class="alert alert-danger small">${esc(
					__("Send is stopped: update these prices first: {0}", [names(price_age.block)])
				)}</div>`,
			},
		];
	}
	if ((price_age.warn || []).length) {
		return [
			{
				fieldname: "price_warn",
				fieldtype: "HTML",
				options: `<div class="alert alert-warning small">${esc(
					__("Old prices on this quote: {0}", [names(price_age.warn)])
				)}</div>`,
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason to send with old prices"),
				reqd: 1,
				description: __("Listed for the admin with the quote."),
			},
		];
	}
	return [];
}

async function sp_quote_share(r, channel, quotation) {
	const blob = await (await fetch(r.file_url, { credentials: "same-origin" })).blob();
	const file = new File([blob], r.file_name, { type: "application/pdf" });
	// a phone: share the PDF straight to WhatsApp (or any app the user picks)
	if (channel === "WhatsApp" && navigator.canShare && navigator.canShare({ files: [file] })) {
		try {
			await navigator.share({ files: [file], title: quotation });
			return;
		} catch (e) {
			// the user closed the share sheet: fall back to the download below
		}
	}
	// a computer: download the PDF, and open WhatsApp Web on the customer's number
	const link = document.createElement("a");
	link.href = URL.createObjectURL(blob);
	link.download = r.file_name;
	link.click();
	if (channel === "WhatsApp") {
		const phone = sp_whatsapp_number(r.mobile);
		window.open(`https://web.whatsapp.com/send${phone ? `?phone=${phone}` : ""}`, "_blank");
	}
}

// An Egyptian mobile (01xxxxxxxxx) in WhatsApp's international form (201xxxxxxxxx)
function sp_whatsapp_number(mobile) {
	const digits = (mobile || "").replace(/\D/g, "");
	return digits.startsWith("0") ? `2${digits}` : digits; // sp-allow-number: Egypt country code
}
