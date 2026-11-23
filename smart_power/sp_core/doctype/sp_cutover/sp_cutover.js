// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// Go-live cutover (SP-163): the runbook's owners tick their steps (when and by whom are kept),
// the admin runs the smoke tests and starts the four weeks of hypercare. The rules are on the
// server (smart_power.sp_core.cutover).
const SP_CUT_API = "smart_power.sp_core.cutover";

frappe.ui.form.on("SP Cutover", {
	refresh(frm) {
		if (frm.is_new()) return;
		const admin = frappe.user.has_role("SP Admin") || frappe.user.has_role("System Manager");
		const mine = (frm.doc.steps || []).filter((r) => !r.done && (admin || r.owner_user === frappe.session.user));
		if (mine.length) {
			frm.add_custom_button(__("Tick a Step"), () => sp_cut_tick(frm, mine)).addClass("btn-primary");
		}
		if (!admin) return;
		frm.add_custom_button(__("Run Smoke Tests"), () => sp_cut_call(frm, "run_smoke"), __("Cutover"));
		frm.add_custom_button(__("Start Hypercare"), () => sp_cut_call(frm, "start_hypercare"), __("Cutover"));
		const done = (frm.doc.steps || []).filter((r) => r.done);
		if (done.length) {
			frm.add_custom_button(__("Untick a Step"), () => sp_cut_untick(frm, done), __("Cutover"));
		}
	},
});

function sp_cut_options(rows) {
	return rows.map((r) => ({ value: r.name, label: `${r.planned_on ? frappe.datetime.str_to_user(r.planned_on) + " · " : ""}${r.step}` }));
}

function sp_cut_tick(frm, rows) {
	const d = new frappe.ui.Dialog({
		title: __("Tick a Step"),
		fields: [
			{ fieldname: "row", fieldtype: "Select", label: __("Step"), options: sp_cut_options(rows), reqd: 1 },
			{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
		],
		primary_action_label: __("Tick"),
		async primary_action(values) {
			if (frm.is_dirty()) await frm.save();
			await frappe.call({ method: `${SP_CUT_API}.tick`, args: { name: frm.doc.name, ...values }, freeze: true });
			d.hide();
			frm.reload_doc();
		},
	});
	d.show();
}

function sp_cut_untick(frm, rows) {
	const d = new frappe.ui.Dialog({
		title: __("Untick a Step"),
		fields: [{ fieldname: "row", fieldtype: "Select", label: __("Step"), options: sp_cut_options(rows), reqd: 1 }],
		primary_action_label: __("Untick"),
		async primary_action(values) {
			await frappe.call({ method: `${SP_CUT_API}.untick`, args: { name: frm.doc.name, ...values }, freeze: true });
			d.hide();
			frm.reload_doc();
		},
	});
	d.show();
}

async function sp_cut_call(frm, method) {
	if (frm.is_dirty()) await frm.save();
	const { message } = await frappe.call({ method: `${SP_CUT_API}.${method}`, args: { name: frm.doc.name }, freeze: true });
	if (message && message.summary) frappe.show_alert({ message: message.summary, indicator: message.passed === message.total ? "green" : "orange" });
	frm.reload_doc();
}
