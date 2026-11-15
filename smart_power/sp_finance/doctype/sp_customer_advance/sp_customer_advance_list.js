// A8 Customer advances (SP-121): the status in colour.
frappe.listview_settings["SP Customer Advance"] = {
	add_fields: ["status"],
	formatters: {
		// the station's number, not its title (the customer's name, already in its own column)
		station: (value) => frappe.utils.escape_html(value || ""),
	},
	get_indicator(doc) {
		const colours = {
			Draft: "gray",
			Open: "blue",
			"Partly repaid": "orange",
			Repaid: "green",
			"Unpaid - overdue": "red",
			Cancelled: "red",
		};
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
