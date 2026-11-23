// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// R3 Installed capacity statement (SP-141): the stations put into operation in a period, by
// system type, as on the company's statement. Print gives the PDF (RTL, with the letterhead),
// Export the Excel file in the same column order.
const SP_IC_HALF = 6; // sp-allow-number: months in a half-year
const SP_IC_JULY = 6; // sp-allow-number: July as a zero-based month

function sp_ic_half_year() {
	const today = frappe.datetime.str_to_obj(frappe.datetime.get_today());
	const first = today.getMonth() >= SP_IC_JULY ? SP_IC_JULY : 0;
	const start = new Date(today.getFullYear(), first, 1);
	const end = new Date(today.getFullYear(), first + SP_IC_HALF, 0);
	return [frappe.datetime.obj_to_str(start), frappe.datetime.obj_to_str(end)];
}

frappe.query_reports["SP Installed Capacity"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: sp_ic_half_year()[0], reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: sp_ic_half_year()[1], reqd: 1 },
		{
			fieldname: "system_type",
			label: __("System Type"),
			fieldtype: "Link",
			options: "SP List Value",
			get_query: () => ({ filters: { list_name: "System Type" } }),
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company") || frappe.boot.sp_company,
		},
	],
	formatter(value, row, column, data, default_formatter) {
		// a section row is its title alone, and the total has no price per kW: no zeros in their place
		if (data && data.is_section && column.fieldname !== "operation_date") return "";
		if (data && data.is_total && column.fieldname === "price_per_kw") return "";
		const out = default_formatter(value, row, column, data);
		return data && (data.is_total || data.is_section) ? `<b>${out}</b>` : out;
	},
};
