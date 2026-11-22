// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// R2 Cash flow (SP-140): by week or month; the overdue row stays out of the running balance.
frappe.query_reports["SP Cash Flow"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "granularity",
			label: __("By"),
			fieldtype: "Select",
			options: [
				{ value: "Week", label: __("Week") },
				{ value: "Month", label: __("Month") },
			],
			default: "Week",
			reqd: 1,
			on_change() {
				const by_week = frappe.query_report.get_filter_value("granularity") === "Week";
				frappe.query_report.set_filter_value("horizon", by_week ? 12 : 6); // sp-allow-number: the default horizons (cash_flow.HORIZONS)
			},
		},
		{
			fieldname: "horizon",
			label: __("Horizon"),
			fieldtype: "Int",
			default: 12, // sp-allow-number: the weekly default
			description: __("4 to 26 weeks, or 1 to 12 months"), // sp-allow-number: the story's limits
		},
		{ fieldname: "include_transit", label: __("Include Transit Accounts"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		let out = default_formatter(value, row, column, data);
		if (data && data.is_overdue) out = `<span class="text-muted">${out}</span>`;
		else if (data && column.fieldname === "closing" && Number(data.closing) < 0)
			out = `<span class="text-danger">${out}</span>`;
		return out;
	},
};
