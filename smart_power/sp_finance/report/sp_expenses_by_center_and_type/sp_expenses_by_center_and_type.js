// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A10 Expenses by center and type (SP-123).
frappe.query_reports["SP Expenses by Center and Type"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.month_end() },
		{
			fieldname: "center_type",
			label: __("Center"),
			fieldtype: "Select",
			options: ["", "Project", "Showroom", "Winch", "Jumbo", "Indirect"],
		},
		{
			fieldname: "expense_type",
			label: __("Expense Type"),
			fieldtype: "Link",
			options: "SP List Value",
			get_query: () => ({ filters: { list_name: "Expense Type" } }),
		},
		{ fieldname: "station", label: __("Station"), fieldtype: "Link", options: "SP Station" },
	],
};
