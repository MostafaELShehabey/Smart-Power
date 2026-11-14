// Quotation (SP-54): versions of a case's quote. The rules are on the server
// (smart_power.sp_sales.quotation); this only adds the buttons and the version note.
// Calculate / Change a Line price a draft from its calculation template (SP-55,
// smart_power.sp_quotes.quote_calc); the Quote Builder (SP-57) replaces these dialogs.
frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (!frm.doc.sp_case || frm.is_new()) return;
		const API = "smart_power.sp_sales.quotation";
		const option = frm.doc.sp_option_label || "A";
		const args = [option, frm.doc.sp_version, frm.doc.sp_case];
		const approved = __("Option {0}, version {1} of case {2}: the approved version.", args); // sp-allow-number: placeholders
		const plain = __("Option {0}, version {1} of case {2}.", args); // sp-allow-number: placeholders
		const note = frm.doc.sp_is_approved ? approved : plain;
		frm.set_intro(note, frm.doc.sp_is_approved ? "green" : "blue");
		if (frm.doc.sp_needs_repricing) {
			frm.set_intro(
				__("Needs repricing: {0}. Make a new version at today's prices.", [
					frm.doc.sp_repricing_note || __("prices changed"),
				]),
				"red"
			);
		}

		if (frm.doc.docstatus < 2) { // sp-allow-number: docstatus cancelled
			frm.add_custom_button(
				frm.doc.docstatus === 0 ? __("Send to Customer") : __("Send Again"),
				() => sp_quote_send(frm)
			);
		}

		frm.add_custom_button(__("New Option"), () =>
			frappe.confirm(
				__("Copy this quote as a full alternative (the next option, e.g. B) on the same case?"),
				async () => {
					const { message: name } = await frappe.call({
						method: `${API}.new_option`,
						args: { quotation: frm.doc.name },
						freeze: true,
					});
					frappe.set_route("Form", "Quotation", name);
				}
			)
		);

		frm.add_custom_button(__("New Version"), async () => {
			const { message: name } = await frappe.call({
				method: `${API}.new_version`,
				args: { quotation: frm.doc.name },
				freeze: true,
			});
			frappe.set_route("Form", "Quotation", name);
		});

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Calculate"), () => sp_quote_calculate(frm), __("Template"));
			if (frm.doc.sp_calc_template) {
				frm.add_custom_button(__("Change a Line"), () => sp_quote_change_line(frm), __("Template"));
			}
		}

		if (frm.doc.docstatus === 1 && !frm.doc.sp_is_approved && !frm.doc.sp_needs_repricing) {
			frm.add_custom_button(__("Approve Version"), () =>
				frappe.confirm(__("Mark this version as the one the customer accepted?"), async () => {
					await frappe.call({
						method: `${API}.approve_version`,
						args: { quotation: frm.doc.name },
						freeze: true,
					});
					frm.reload_doc();
				})
			);
		}
	},
});

const SP_QC_API = "smart_power.sp_quotes.quote_calc";
const SP_QC_TYPES = { Float: "Float", Int: "Int", Check: "Check", Select: "Select", Data: "Data" };

async function sp_quote_calculate(frm) {
	const stored = frm.doc.sp_design_inputs ? JSON.parse(frm.doc.sp_design_inputs) : {};
	let template = frm.doc.sp_calc_template;
	if (!template) {
		const values = await new Promise((resolve) =>
			frappe.prompt(
				{
					fieldname: "template",
					fieldtype: "Link",
					options: "SP Calc Template",
					label: __("Calculation Template"),
					description: __("Empty uses the published template of the case's system type."),
					get_query: () => ({ filters: { is_published: 1 } }),
				},
				resolve,
				__("Calculate"),
				__("Next")
			)
		);
		template = values.template;
	}
	// no template picked: the one the server will use (the published one for the case's system
	// type), so its inputs are still asked for
	const { message: info } = await frappe.call({
		method: `${SP_QC_API}.template_for_quote`,
		args: { quotation: frm.doc.name, template: template || null },
	});
	template = info.template;
	const inputs = info.inputs || [];
	const dialog = new frappe.ui.Dialog({
		title: __("Design Inputs"),
		fields: inputs.map((i) => ({
			fieldname: i.input_key,
			label: i.label,
			fieldtype: SP_QC_TYPES[i.input_type] || "Data",
			options: i.options,
			default: stored[i.input_key] ?? i.default_value,
			reqd: i.reqd,
			description: i.help,
		})),
		primary_action_label: __("Calculate"),
		primary_action: async (values) => {
			dialog.hide();
			const { message: r } = await frappe.call({
				method: `${SP_QC_API}.calculate_quote`,
				args: { quotation: frm.doc.name, inputs: values, template },
				freeze: true,
			});
			await frm.reload_doc();
			sp_quote_notes(r);
		},
	});
	if (inputs.length) dialog.show();
	else dialog.primary_action({});
}

function sp_quote_change_line(frm) {
	// the calculated lines, including the optional ones under the total (SP-59)
	const lines = [
		...frm.doc.items.filter((row) => row.sp_line_key).map((row) => row.sp_line_key),
		...(frm.doc.sp_optional_lines || []).filter((row) => row.line_key).map((row) => row.line_key),
	];
	const dialog = new frappe.ui.Dialog({
		title: __("Change a Line"),
		fields: [
			{ fieldname: "line_key", fieldtype: "Select", label: __("Line"), options: lines, reqd: 1 },
			{
				fieldname: "field",
				fieldtype: "Select",
				label: __("Change"),
				reqd: 1,
				options: [
					{ value: "qty", label: __("Qty") },
					{ value: "item_code", label: __("Item") },
					{ value: "markup", label: __("Markup %") },
					{ value: "rate", label: __("Price (manual lines)") },
					{ value: "cost", label: __("Cost (manual lines)") },
				],
			},
			{
				fieldname: "value",
				fieldtype: "Data",
				label: __("New Value"),
				description: __("Empty goes back to the template."),
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				depends_on: "eval:doc.field=='markup'",
				mandatory_depends_on: "eval:doc.field=='markup'",
			},
		],
		primary_action_label: __("Save"),
		primary_action: async (values) => {
			dialog.hide();
			const { message: r } = await frappe.call({
				method: `${SP_QC_API}.set_line_override`,
				args: { quotation: frm.doc.name, ...values },
				freeze: true,
			});
			await frm.reload_doc();
			sp_quote_notes(r);
		},
	});
	dialog.show();
}

function sp_quote_notes(r) {
	const notes = (r && r.rule_results) || [];
	if (!notes.length) return;
	const esc = frappe.utils.escape_html;
	frappe.msgprint({
		title: __("Calculation Notes"),
		indicator: notes.some((n) => n.level === "warn") ? "orange" : "blue",
		message: `<ul>${notes.map((n) => `<li>${esc(n.line_key)}: ${esc(n.message)}</li>`).join("")}</ul>`,
	});
}

// Send a quote version (SP-61): the server submits a draft, prints the PDF, logs the send and
// moves the case; here the PDF is shared to WhatsApp (phone) or downloaded with WhatsApp Web
// opened (computer).
const SP_SEND_API = "smart_power.sp_quotes.quote_send";

async function sp_quote_send(frm) {
	const { message: opts } = await frappe.call(`${SP_SEND_API}.send_options`, { quotation: frm.doc.name });
	const dialog = new frappe.ui.Dialog({
		title: frm.doc.docstatus === 0 ? __("Send to Customer") : __("Send Again"),
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
					frm.doc.docstatus === 0
						? __("Sending freezes this version: it cannot be edited afterwards.")
						: __("A new PDF is made and logged for this send.")
				)}</p>`,
			},
		],
		primary_action_label: __("Send"),
		primary_action: async (values) => {
			dialog.hide();
			const { message: r } = await frappe.call({
				method: `${SP_SEND_API}.send_quote`,
				args: { quotation: frm.doc.name, ...values },
				freeze: true,
				freeze_message: __("Making the PDF…"),
			});
			(r.warnings || []).forEach((w) => frappe.show_alert({ message: w, indicator: "orange" }, 10)); // sp-allow-number: seconds on screen
			frappe.show_alert({ message: __("Quote sent"), indicator: "green" });
			await sp_quote_share(r, values.channel, frm);
			frm.reload_doc();
		},
	});
	dialog.show();
}

async function sp_quote_share(r, channel, frm) {
	const blob = await (await fetch(r.file_url, { credentials: "same-origin" })).blob();
	const file = new File([blob], r.file_name, { type: "application/pdf" });
	// a phone: share the PDF straight to WhatsApp (or any app the user picks)
	if (channel === "WhatsApp" && navigator.canShare && navigator.canShare({ files: [file] })) {
		try {
			await navigator.share({ files: [file], title: frm.doc.name });
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
