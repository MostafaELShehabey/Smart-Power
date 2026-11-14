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
				__("Calculate")
			)
		);
		template = values.template;
	}
	const inputs = template ? (await frappe.db.get_doc("SP Calc Template", template)).inputs : [];
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
	const lines = frm.doc.items.filter((row) => row.sp_line_key).map((row) => row.sp_line_key);
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
