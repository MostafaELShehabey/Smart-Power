// Calculation template (SP-55, X7): Publish / Unpublish / New Version.
// The rules are on the server (sp_calc_template.py).

frappe.ui.form.on("SP Calc Template", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Test with Sample Inputs"), () => sp_calc_sample(frm));
		if (frm.doc.is_published) {
			frm.set_intro(__("Published: this version cannot change. Make a new version to edit."), "blue");
			frm.disable_form();
			frm.add_custom_button(__("Unpublish"), () => frm.call("unpublish").then(() => frm.reload_doc()));
		} else {
			frm.add_custom_button(__("Publish"), () =>
				frappe.confirm(
					__("Publish version {0}? The published version of this offer type stops.", [frm.doc.version]),
					() => frm.call("publish").then(() => frm.reload_doc())
				)
			);
		}
		frm.add_custom_button(__("New Version"), () =>
			frm.call("new_version").then((r) => frappe.set_route("Form", "SP Calc Template", r.message))
		);
	},
});

// Price the template with sample inputs and show the lines, totals and warnings.
function sp_calc_sample(frm) {
	const types = { Float: "Float", Int: "Int", Check: "Check", Select: "Select", Data: "Data" };
	const dialog = new frappe.ui.Dialog({
		title: __("Test with Sample Inputs"),
		fields: (frm.doc.inputs || []).map((i) => ({
			fieldname: i.input_key,
			label: i.label,
			fieldtype: types[i.input_type] || "Data",
			options: i.options,
			default: i.default_value,
			reqd: i.reqd,
			description: i.help,
		})),
		primary_action_label: __("Calculate"),
		primary_action: async (inputs) => {
			const { message: r } = await frm.call("run_sample", { inputs });
			dialog.hide();
			sp_calc_show(r);
		},
	});
	dialog.show();
}

function sp_calc_show(r) {
	const esc = frappe.utils.escape_html;
	const num = (v) => format_number(v || 0, null, 2); // sp-allow-number: display decimals
	const rows = r.lines
		.map(
			(l) => `<tr class="${l.is_optional ? "text-muted" : ""}">
				<td>${esc(l.line_key)}</td><td>${esc(l.item_code || l.item_name || "")}</td>
				<td class="text-right">${num(l.qty)}${l.is_manual_qty ? " ✎" : ""}</td>
				<td class="text-right">${num(l.cost)}</td><td class="text-right">${num(l.rate)}${
				l.lock_markup ? " 🔒" : ""
			}</td>
				<td class="text-right">${num(l.amount)}</td></tr>`
		)
		.join("");
	const warnings = (r.rule_results || [])
		.map((w) => `<li>${esc(w.line_key)}: ${esc(w.message)}</li>`)
		.join("");
	const t = r.totals;
	frappe.msgprint({
		title: __("Result"),
		wide: true,
		message: `<table class="table table-sm"><thead><tr><th>${__("Line Key")}</th><th>${__(
			"Item"
		)}</th><th class="text-right">${__("Qty")}</th><th class="text-right">${__(
			"Cost"
		)}</th><th class="text-right">${__("Price")}</th><th class="text-right">${__(
			"Amount"
		)}</th></tr></thead><tbody>${rows}</tbody></table>
			<p>${__("Total cost {0} · Total sale {1} · Profit {2} · Margin {3}%", [ // sp-allow-number: placeholders
				num(t.cost),
				num(t.sell),
				num(t.profit),
				num(t.margin_pct),
			])}</p>${warnings ? `<ul class="text-warning">${warnings}</ul>` : ""}`,
	});
}
