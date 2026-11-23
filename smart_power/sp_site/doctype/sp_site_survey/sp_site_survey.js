// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// C4 Site survey (SP-95): fill the well data or the load table, the pin and the photos (as
// attachments), then submit: the data joins the request and the quote creator is told.
frappe.ui.form.on("SP Site Survey", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Open") return;
		frm.add_custom_button(__("Submit Survey"), async () => {
			if (frm.is_dirty()) await frm.save();
			await frappe.call({ method: "smart_power.sp_site.site_survey.complete", args: { name: frm.doc.name }, freeze: true });
			frm.reload_doc();
		}).addClass("btn-primary");
	},
});
