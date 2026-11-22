// Theoretical vs scale weight of chassis iron (SP-178)
frappe.query_reports["SP Iron Weight Variance"] = {
	filters: [
		{ fieldname: "factory", label: __("Factory"), fieldtype: "Link", options: "SP Chassis Factory" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "warning" && data && data.warning) value = `<span class="text-danger">${value}</span>`;
		return value;
	},
};
