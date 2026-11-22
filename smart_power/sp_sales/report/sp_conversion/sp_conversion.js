// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// R6 Conversion (SP-144): the requests of the period, followed to today.
frappe.query_reports["SP Conversion"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.month_end(), reqd: 1 },
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: [
				{ value: "Channel", label: __("Channel") },
				{ value: "Requester", label: __("Requester") },
				{ value: "Quote creator", label: __("Quote creator") },
				{ value: "Follow-up owner", label: __("Follow-up owner") },
				{ value: "Lost reason", label: __("Lost reason") },
			],
			default: "Channel",
			reqd: 1,
		},
		{
			fieldname: "system_type",
			label: __("System Type"),
			fieldtype: "Link",
			options: "SP List Value",
			get_query: () => ({ filters: { list_name: "System Type" } }),
		},
		{
			fieldname: "region",
			label: __("Region"),
			fieldtype: "Link",
			options: "SP List Value",
			get_query: () => ({ filters: { list_name: "Region" } }),
		},
	],
	formatter(value, row, column, data, default_formatter) {
		const out = default_formatter(value, row, column, data);
		return data && data.is_total ? `<b>${out}</b>` : out;
	},
};
