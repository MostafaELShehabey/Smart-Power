// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// RG1 semi-annual reports (SP-101): the status in its colour on the list.
frappe.listview_settings["SP Compliance Report"] = {
	get_indicator(doc) {
		const colours = { Draft: "orange", Submitted: "green" };
		return [__(doc.status), colours[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
