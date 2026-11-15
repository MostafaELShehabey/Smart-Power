// A9 Custody settlements (SP-122): the status in colour.
frappe.listview_settings["SP Custody Settlement"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colours = { Draft: "gray", Pending: "orange", Approved: "green", Rejected: "red" };
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
