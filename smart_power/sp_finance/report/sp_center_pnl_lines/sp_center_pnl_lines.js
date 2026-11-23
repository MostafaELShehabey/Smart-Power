// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// R4 Center P&L drill-down (SP-142): the GL lines behind one amount of the Center P&L.
frappe.query_reports["SP Center PnL Lines"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company") || frappe.boot.sp_company,
			reqd: 1,
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.month_end(), reqd: 1 },
		{
			fieldname: "center",
			label: __("Center"),
			fieldtype: "Select",
			options: [
				{ value: "", label: "" },
				{ value: "projects", label: __("Projects") },
				{ value: "showroom", label: __("Showroom") },
				{ value: "winch", label: __("Winch") },
				{ value: "jumbo", label: __("Jumbo Car") },
				{ value: "indirect", label: __("Indirect Pool") },
				{ value: "other", label: __("Other") },
			],
		},
		{ fieldname: "station", label: __("Station"), fieldtype: "Link", options: "SP Station" },
		{
			fieldname: "kind",
			label: __("Column"),
			fieldtype: "Select",
			options: [
				{ value: "", label: "" },
				{ value: "Revenue", label: __("Revenue") },
				{ value: "Direct Cost", label: __("Direct Cost") },
				{ value: "Indirect Share", label: __("Indirect Share") },
			],
		},
		{ fieldname: "no_station", label: __("No station"), fieldtype: "Check" },
		{ fieldname: "internal_only", label: __("Internal charges only"), fieldtype: "Check" },
	],
};
