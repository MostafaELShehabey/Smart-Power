// W2 month grid (SP-111): the vehicle's month in the winch sheet's columns.
// The figures are on the server (smart_power.sp_winch.month_grid).

frappe.query_reports["SP Winch Month Grid"] = {
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
			options: sp_winch_years(),
			default: String(new Date().getFullYear()),
			reqd: 1,
		},
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: [
				{ value: "1", label: __("January") },
				{ value: "2", label: __("February") },
				{ value: "3", label: __("March") },
				{ value: "4", label: __("April") },
				{ value: "5", label: __("May") },
				{ value: "6", label: __("June") },
				{ value: "7", label: __("July") },
				{ value: "8", label: __("August") },
				{ value: "9", label: __("September") },
				{ value: "10", label: __("October") },
				{ value: "11", label: __("November") },
				{ value: "12", label: __("December") },
			],
			default: String(new Date().getMonth() + 1),
			reqd: 1,
		},
	],
};

function sp_winch_years() {
	const current = new Date().getFullYear();
	const first = 2026; // sp-allow-number: the first year with field entries in the system
	const years = [];
	for (let year = current + 1; year >= first; year--) years.push(String(year));
	return years;
}
