// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// RG1 qualification documents (SP-101): the status in its colour on the list.
frappe.listview_settings["SP Compliance Document"] = {
	get_indicator(doc) {
		const colours = { Valid: "green", Expiring: "orange", Expired: "red" };
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
