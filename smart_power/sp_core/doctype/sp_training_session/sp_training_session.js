// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A training session (SP-162): the grid's Top Task columns carry the guide's own task names.
frappe.ui.form.on("SP Training Session", {
	refresh(frm) {
		sp_trn_labels(frm);
	},
	guide(frm) {
		if (frm.doc.guide) frm.save().then(() => sp_trn_labels(frm));
	},
});

function sp_trn_labels(frm) {
	const grid = frm.fields_dict.attendees.grid;
	["task_1", "task_2", "task_3"].forEach((field) => {
		const name = frm.doc[`top_${field}`];
		if (name) grid.update_docfield_property(field, "label", name);
	});
	grid.refresh();
}
