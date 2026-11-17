// A marketing lead (SP-51): "Convert to request" opens C3 with the lead's mobile, name, source,
// campaign and follow-up owner; saving the request links it back to the lead.
frappe.ui.form.on("Lead", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.sp_case) {
			frm.set_intro(__("This lead is request {0}.", [frm.doc.sp_case]), "green");
			return;
		}
		if (!frappe.model.can_create("SP Case")) return;
		frm.add_custom_button(__("Convert to request"), async () => {
			const { message: opts } = await frappe.call("smart_power.sp_sales.leads.convert_options", {
				lead: frm.doc.name,
			});
			frappe.route_options = opts;
			frappe.set_route("sp-quote-request");
		});
	},
});
