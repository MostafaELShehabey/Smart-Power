// The reconciliation's status, coloured on the list and on the form (SP-93).
frappe.listview_settings["SP Consignment Reconciliation"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = { Draft: "orange", Matched: "green", "With differences": "red" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
