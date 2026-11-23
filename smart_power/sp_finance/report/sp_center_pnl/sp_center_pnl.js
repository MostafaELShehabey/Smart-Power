// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// R4 Center P&L (SP-142): every amount opens the GL lines behind it.
const SP_PNL_DRILL = {
	revenue: "Revenue",
	cost: "Direct Cost",
	indirect: "Indirect Share",
	internal_in: "Revenue",
	internal_out: "Direct Cost",
};

frappe.query_reports["SP Center PnL"] = {
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
	],
	formatter(value, row, column, data, default_formatter) {
		let out = default_formatter(value, row, column, data);
		if (!data) return out;
		const kind = SP_PNL_DRILL[column.fieldname];
		if (kind && Number(data[column.fieldname])) {
			const args = {
				company: frappe.query_report.get_filter_value("company"),
				from_date: frappe.query_report.get_filter_value("from_date"),
				to_date: frappe.query_report.get_filter_value("to_date"),
				kind,
			};
			if (!["total", "elimination"].includes(data.center_key)) args.center = data.center_key;
			if (data.station) args.station = data.station;
			if (data.no_station) args.no_station = 1;
			if (column.fieldname.startsWith("internal") || data.center_key === "elimination") args.internal_only = 1;
			out = `<a href="/app/query-report/SP Center PnL Lines?${new URLSearchParams(args)}">${out}</a>`;
		}
		if (!data.indent) out = `<b>${out}</b>`;
		return out;
	},
};
