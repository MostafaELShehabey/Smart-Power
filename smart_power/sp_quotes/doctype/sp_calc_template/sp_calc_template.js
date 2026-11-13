// Calculation template (SP-55, X7): Publish / Unpublish / New Version.
// The rules are on the server (sp_calc_template.py).

frappe.ui.form.on("SP Calc Template", {
	refresh(frm) {
		if (frm.is_new()) return;
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
