// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// R1 Station financial position (SP-139): the owner's "ميزان الحركة", one row per station.
frappe.query_reports["SP Station Position"] = {
	filters: [
		{ fieldname: "year", label: __("Year"), fieldtype: "Int", default: new Date().getFullYear() },
		{
			fieldname: "financing",
			label: __("Financing"),
			fieldtype: "Link",
			options: "SP List Value",
			get_query: () => ({ filters: { list_name: "Financing Type" } }),
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Open", "Purchasing", "Installing", "Technically closed", "Financially closed", "Cancelled"],
		},
	],
};
