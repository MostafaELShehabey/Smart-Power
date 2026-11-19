// The year summary (SP-111): twelve months of the vehicle's key figures. A month's row opens the
// month grid. The figures are on the server (smart_power.sp_winch.month_grid).

frappe.query_reports["SP Winch Year Summary"] = {
	filters: [
		{
			fieldname: "vehicle",
			label: __("Vehicle"),
			fieldtype: "Link",
			options: "Vehicle",
			reqd: 1,
		},
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Select",
			options: sp_winch_summary_years(),
			default: String(new Date().getFullYear()),
			reqd: 1,
		},
	],
	formatter(value, row, column, data, default_formatter) {
		const rendered = default_formatter(value, row, column, data);
		if (column.fieldname !== "month" || !data || !data.month_number) return rendered;
		const vehicle = frappe.query_report.get_filter_value("vehicle");
		const year = frappe.query_report.get_filter_value("year");
		const params = new URLSearchParams({ vehicle, year, month: String(data.month_number) });
		return `<a href="/app/query-report/SP Winch Month Grid?${params}">${rendered}</a>`;
	},
};

function sp_winch_summary_years() {
	const current = new Date().getFullYear();
	const first = 2026; // sp-allow-number: the first year with field entries in the system
	const years = [];
	for (let year = current + 1; year >= first; year--) years.push(String(year));
	return years;
}
