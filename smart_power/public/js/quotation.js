// Quotation (SP-54): versions of a case's quote. The rules are on the server
// (smart_power.sp_sales.quotation); this only adds the buttons and the version note.
// Calculate / Change a Line price a draft from its calculation template (SP-55,
// smart_power.sp_quotes.quote_calc); the Quote Builder (SP-57) replaces these dialogs.
frappe.ui.form.on("Quotation", {
	setup(frm) {
		// a clock on the lines whose price is old: red stale, amber aging (SP-63)
		frm.set_indicator_formatter(
			"item_code",
			(doc) => ({ stale: "red", aging: "orange" })[doc.sp_price_status] || "",
			(doc) =>
				["stale", "aging"].includes(doc.sp_price_status)
					? `${doc.item_code} 🕒 ${__("{0} days", [doc.sp_price_age_days])}`
					: doc.item_code
		);
	},

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
		// the margin against its range: orange out of range, never blocking a send (SP-63)
		sp_quote_margin_chip(frm);
		// the indicative price given first, and how far this version is from it (SP-49)
		const indicative = frm.doc.__onload?.sp_indicative;
		if (indicative) {
			const money = (v) => format_currency(v, frm.doc.currency);
			const diff = indicative.difference;
			const args = [money(indicative.price), frappe.datetime.str_to_user(indicative.on), indicative.by || ""];
			const given = __("Indicative price {0} given on {1} by {2}.", args); // sp-allow-number: placeholders
			const same = Math.abs(diff) < 0.5; // sp-allow-number: under half a pound is the same price
			const versus = same
				? __("This version is the same.")
				: diff > 0
				? __("This version is {0} higher.", [money(diff)])
				: __("This version is {0} lower.", [money(-diff)]);
			// the headline, so the version note above it stays
			frm.dashboard.add_comment(frappe.utils.escape_html(`${given} ${versus}`), same ? "green" : "orange", true);
		}
		// after the contract: read-only, with whom the case is now (SP-35)
		if (frm.doc.__onload?.sp_read_only) {
			frm.set_intro(frm.doc.__onload.sp_read_only, "orange");
			frm.disable_form();
		}

		// a draft's primary button sends it (SP-45); a sent one can be sent again
		if (frm.doc.docstatus === 1) frm.add_custom_button(__("Send Again"), () => sp_quote_send(frm));

		if (frm.doc.docstatus < 2) { // sp-allow-number: docstatus cancelled
			frm.add_custom_button(__("Give Discount"), () =>
				smart_power.discount_dialog(frm.doc.name, (result) =>
					result.quotation === frm.doc.name
						? frm.reload_doc()
						: frappe.set_route("Form", "Quotation", result.quotation)
				)
			);
		}

		frm.add_custom_button(__("Quote Builder"), () => frappe.set_route("sp-quote-builder", frm.doc.name));

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

		// the same quote for another customer, in a new case (Q1, SP-64)
		if (frappe.model.can_create("Quotation")) {
			frm.add_custom_button(__("Duplicate for Customer"), () => sp.sales.duplicate_quote(frm.doc.name));
		}

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

		// a sent version's primary button marks it won (SP-45); an expired one keeps this button
		const approvable = frm.doc.docstatus === 1 && !frm.doc.sp_is_approved && !frm.doc.sp_needs_repricing;
		if (approvable && frm.doc.sp_status !== "Sent") {
			frm.add_custom_button(__("Approve Version"), () => sp_quote_approve(frm));
		}
	},
});

function sp_quote_approve(frm) {
	frappe.confirm(__("Mark this version as the one the customer accepted?"), async () => {
		await frappe.call({
			method: "smart_power.sp_sales.quotation.approve_version",
			args: { quotation: frm.doc.name },
			freeze: true,
		});
		frm.reload_doc();
	});
}

// The record pattern's primary button (SP-45): Draft → Send quote, Sent → Approve Version (the
// case is won by the deposit on it, SP-70).
sp.form.register_primary(
	"Quotation",
	"sp_status",
	{
		Draft: { label: __("Send quote"), action: sp_quote_send },
		Sent: { label: __("Approve Version"), action: sp_quote_approve },
	},
	(frm) => frm.doc.sp_case
);

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
function sp_quote_send(frm) {
	return sp.sales.send_quote(frm.doc.name, frm.doc.docstatus, () => frm.reload_doc());
}

// Special lines (SP-58): picking a line kind puts its service item on the row; the line's own text
// replaces the name. A commission is cost only: its amount (typed as Cost, or as Rate) moves to
// the cost on save, and it is never printed (smart_power.sp_quotes.special_lines).
frappe.ui.form.on("Quotation Item", {
	async sp_line_kind(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.sp_line_kind) return;
		frappe.provide("smart_power");
		smart_power._service_items ??= await frappe.xcall(
			"smart_power.sp_quotes.special_lines.get_service_items"
		);
		const item = smart_power._service_items[row.sp_line_kind];
		if (item && row.item_code !== item) await frappe.model.set_value(cdt, cdn, "item_code", item);
	},
});

// beside the margin, in the cost section (cost permlevel): its creator and the admin see it
function sp_quote_margin_chip(frm) {
	const field = frm.fields_dict.sp_margin_chip;
	if (!field) return;
	const check = frm.doc.__onload?.sp_margin_check;
	if (!check) {
		field.$wrapper.empty();
		return;
	}
	const range = `${check.min}% – ${check.max}%`;
	const label = check.in_range
		? __("Margin {0}% in range ({1})", [check.margin, range])
		: __("Margin {0}% out of range ({1})", [check.margin, range]);
	field.$wrapper.html(
		`<div class="mb-3"><span class="indicator-pill ${check.in_range ? "green" : "orange"}">${frappe.utils.escape_html(label)}</span></div>`
	);
	// out of range: open the (collapsed) Cost and Profit section so the chip is seen, once the
	// form has finished refreshing (the layout sets the sections' collapse after this script)
	if (!check.in_range) setTimeout(() => frm.fields_dict.sp_cost_section?.collapse(false), 0);
}
