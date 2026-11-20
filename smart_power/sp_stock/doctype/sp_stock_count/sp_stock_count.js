// The count is made on its sheet (Stock Counts page), never on this form: the form only shows it (SP-94).
frappe.ui.form.on("SP Stock Count", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.disable_save();
		const label = frm.doc.status === "Draft" ? __("Open Count Sheet") : __("Stock Counts");
		frm.add_custom_button(label, () => frappe.set_route("sp-count-sheets", frm.doc.status === "Draft" ? frm.doc.name : undefined)).addClass("btn-primary");
	},
});
