// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// SV1 Service ticket (SP-72): follow-up opens it for one of the customer's stations; installations
// accept, work and close it (the work log and parts are SP-99). The rules are on the server.
const SP_SVC_NEXT = { Open: "Accepted", Accepted: "In progress", "In progress": "Closed" };
const SP_SVC_LABEL = { Accepted: "Accept", "In progress": "Start Work", Closed: "Close Ticket" };

frappe.ui.form.on("SP Service Ticket", {
	setup(frm) {
		frm.set_query("station", () => ({ filters: { customer: frm.doc.customer || "" } }));
		frm.set_query("issue_type", () => ({ filters: { list_name: "Service Issue", is_active: 1 } }));
	},
	customer(frm) {
		frm.set_value("station", null);
	},
	refresh(frm) {
		const next = SP_SVC_NEXT[frm.doc.status];
		const installer = ["SP Installation Manager", "SP Warranty Service", "SP Admin", "System Manager"].some((r) => frappe.user.has_role(r));
		if (frm.is_new() || !next || !installer) return;
		frm.add_custom_button(__(SP_SVC_LABEL[next]), async () => {
			await frappe.call({ method: "smart_power.sp_site.service.move", args: { name: frm.doc.name, status: next }, freeze: true });
			frm.reload_doc();
		}).addClass("btn-primary");
	},
});
