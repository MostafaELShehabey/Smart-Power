// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// RG1 semi-annual report (SP-101): "Generate Statement" opens the installed capacity statement
// (R3) for the report's period; "Attach Statement" puts its Excel export on the report.
frappe.ui.form.on("SP Compliance Report", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Generate Statement"), () => {
			frappe.set_route("query-report", "SP Installed Capacity", {
				from_date: frm.doc.period_from,
				to_date: frm.doc.period_to,
			});
		});
		if (frm.doc.status !== "Draft") return;
		frm.add_custom_button(__("Attach Statement"), () => {
			frappe.call({
				method: "smart_power.sp_stations.compliance.attach_statement",
				args: { name: frm.doc.name },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		});
	},
});
