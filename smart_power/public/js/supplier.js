// The supplier's ledger, one click from their record (SP-86).
frappe.ui.form.on("Supplier", {
	refresh(frm) {
		if (frm.is_new()) return;
		const viewers = ["SP Supplier Accounts", "SP Accountant", "SP Admin", "System Manager"];
		if (!viewers.some((role) => frappe.user.has_role(role))) return;
		frm.add_custom_button(__("Supplier Ledger"), () => {
			frappe.route_options = { supplier: frm.doc.name };
			frappe.set_route("sp-supplier-ledger");
		});
	},
});
