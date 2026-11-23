// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// RG1 qualification document (SP-101): the status colour in the form's header.
frappe.ui.form.on("SP Compliance Document", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.expiry_date) return;
		const colours = { Valid: "green", Expiring: "orange", Expired: "red" };
		frm.page.set_indicator(__(frm.doc.status), colours[frm.doc.status] || "gray");
	},
});
