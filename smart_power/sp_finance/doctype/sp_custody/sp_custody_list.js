// A9 Custody (SP-122): the status in colour.
frappe.listview_settings["SP Custody"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colours = {
			Draft: "gray",
			Given: "blue",
			Spending: "orange",
			"Settlement submitted": "purple",
			Approved: "green",
			Carried: "green",
			Returned: "gray",
			Cancelled: "red",
		};
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
